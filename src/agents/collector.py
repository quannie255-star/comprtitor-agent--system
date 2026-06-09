"""
采集 Agent (Collector)

职责：根据目标产品名称，自动完成 搜索 → 抓取 → 解析 全链路，
     输出结构化的 CompetitorProfile。

继承自 BaseAgent，通过消息总线发送采集结果给下游 Agent。
"""

from datetime import datetime
from typing import Any, Optional

from loguru import logger

from agents.base import BaseAgent
from core.message_bus import MessageType
from core.schema import CompetitorProfile, Evidence
from tools.data_parser import DataParser
from tools.web_scraper import WebScraperTool
from tools.web_search import WebSearchTool


class CollectorAgent(BaseAgent):
    """采集 Agent

    输入: state["target_product"]
    输出: state["competitor_profiles"] + state["source_pool"]

    执行流程:
      1. 搜索目标产品 → 获取 URL 列表
      2. 抓取 Top-N 页面内容
      3. LLM 解析 → 结构化 CompetitorProfile
      4. 汇总 Evidence 到 source_pool
    """

    def __init__(
        self,
        message_bus=None,
        llm=None,
        config: Optional[dict] = None,
        search_tool: Optional[WebSearchTool] = None,
        scraper_tool: Optional[WebScraperTool] = None,
        parser: Optional[DataParser] = None,
    ):
        super().__init__(
            name="collector",
            message_bus=message_bus,
            llm=llm,
            config=config,
        )
        self.search_tool = search_tool or WebSearchTool(
            api_key=config.get("search", {}).get("api_key", "") if config else "",
        )
        self.scraper_tool = scraper_tool or WebScraperTool()
        self.parser = parser or DataParser()

    def execute(self, state: dict, **kwargs) -> dict:
        """执行采集流程

        Args:
            state: LangGraph AgentState（或部分 state）
            target_products: 显式传入的竞品列表（优先级高于 state）

        Returns:
            更新后的 state 片段
        """
        # 优先用显式传入，其次读 state
        raw_targets = kwargs.get("target_products") or state.get("target_products") or [state.get("target_product", "")]
        if isinstance(raw_targets, str):
            raw_targets = [raw_targets]  # 单字符串 → 单元素列表
        # 过滤：长度 < 2 或纯空白的不算有效竞品名
        targets = [t for t in raw_targets if isinstance(t, str) and len(t.strip()) >= 2]
        if not targets:
            raise ValueError("state 中缺少有效的 target_product 或 target_products")

        logger.info(f"[Collector] 开始采集 {len(targets)} 个竞品: {targets}")

        all_profiles = []
        source_pool = []
        seen_urls = set()

        for target in targets:
            logger.info(f"[Collector] 正在采集: {target}")

            # --- Step 1: 搜索 ---
            search_start = datetime.now()
            self._log_step(action="search_start", input_summary=f"搜索: {target}")

            search_results = self._search(target, seen_urls)

            self._log_step(
                action="search_complete",
                input_summary=f"搜索: {target}",
                output_summary=f"获取 {len(search_results)} 条结果",
                started_at=search_start,
                duration_ms=(datetime.now() - search_start).total_seconds() * 1000,
            )

            # --- Step 2: 抓取 ---
            scrape_start = datetime.now()
            self._log_step(
                action="scrape_start",
                input_summary=f"抓取 {min(3, len(search_results))} 个页面",
            )

            urls = [r.get("url", "") for r in search_results[:3] if isinstance(r, dict)]
            scraped = self.scraper_tool.fetch_multiple(urls)

            self._log_step(
                action="scrape_complete",
                output_summary=f"成功抓取 {sum(1 for s in scraped if isinstance(s, dict) and not s.get('error'))} 个页面",
                started_at=scrape_start,
                duration_ms=(datetime.now() - scrape_start).total_seconds() * 1000,
            )

            # --- Step 3: 解析 ---
            parse_start = datetime.now()
            self._log_step(action="parse_start", input_summary=f"LLM 解析: {target}")

            combined_text = self._merge_scraped_content(search_results, scraped)

            try:
                first_scraped = next((s for s in scraped if isinstance(s, dict) and not s.get("error")), None)
                first_result = search_results[0] if search_results else {}
                source_url = (first_scraped or first_result).get("url", "")
                source_title = (first_scraped or first_result).get("title", target)
            except Exception as e:
                logger.error(f"数据提取失败: {e} | scraped type={type(scraped)}, "
                           f"search_results type={type(search_results)}, "
                           f"scraped[0]={type(scraped[0]) if scraped else 'empty'}, "
                           f"search_results[0]={type(search_results[0]) if search_results else 'empty'}")
                raise

            profile = self.parser.parse_to_profile(
                llm=self.llm,
                target_product=target,
                raw_text=combined_text,
                source_url=source_url,
                source_title=source_title,
            )

            # DataParser 返回 None 时，构建最小化但 name 准确的 Profile
            if profile is None:
                evidence = Evidence(
                    source_id=f"src_{hash(source_url or target) % 100000:05d}",
                    source_url=source_url or "",
                    source_title=source_title or target,
                    excerpt=combined_text[:500],
                    retrieved_at=datetime.now(),
                    confidence=0.5,
                )
                profile = CompetitorProfile(
                    name=target,
                    description="待 LLM 分析补充",
                    data_sources=[evidence],
                )

            self._log_step(
                action="parse_complete",
                output_summary=f"生成 CompetitorProfile: {len(profile.core_features)} 功能",
                evidence_refs=[e.source_id for e in profile.data_sources],
                started_at=parse_start,
                duration_ms=(datetime.now() - parse_start).total_seconds() * 1000,
            )

            all_profiles.append(profile)

            # --- Step 4: 构建 source_pool（跨竞品共享，去重）---
            for sr in search_results:
                if not isinstance(sr, dict):
                    continue  # 跳过非 dict 元素
                if sr.get("url", "") not in seen_urls:
                    seen_urls.add(sr.get("url", ""))
                    evidence = Evidence(
                        source_id=f"src_{hash(sr.get('url', '')) % 100000:05d}",
                        source_url=sr.get("url", ""),
                        source_title=str(sr.get("title", "")),
                        excerpt=str(sr.get("content", ""))[:500],
                        retrieved_at=datetime.now(),
                        confidence=sr.get("score", 0.7),
                    )
                    source_pool.append(evidence)

        logger.info(f"[Collector] 采集完成: {len(all_profiles)} 个 Profile: {[p.name for p in all_profiles]}")
        logger.info(f"[Collector] source_pool: {len(source_pool)} 条, 唯一 URL: {len(seen_urls)}")

        # --- Step 5: 发送消息 ---
        self.send_message(
            receiver="analyst",
            msg_type=MessageType.DATA_OUTPUT,
            payload={
                "target_products": targets,
                "profile_count": len(all_profiles),
                "source_count": len(source_pool),
            },
        )

        return {
            "source_pool": [e.model_dump(mode="json") for e in source_pool],
            "competitor_profiles": [p.model_dump(mode="json") for p in all_profiles],
        }

    # --- 内部方法 ---

    def _search(self, target: str, seen_urls: set | None = None) -> list[dict]:
        """搜索目标产品"""
        seen = seen_urls or set()
        queries = [
            f"{target} 产品功能介绍",
            f"{target} 定价方案",
            f"{target} 优缺点评测",
        ]
        all_results = []

        for query in queries:
            results = self.search_tool.search(query, max_results=3)
            for r in results:
                if r["url"] not in seen:
                    seen.add(r["url"])
                    all_results.append(r)

        logger.info(f"[Collector] 去重后共 {len(all_results)} 条搜索结果")
        return all_results

    @staticmethod
    def _merge_scraped_content(
        search_results: list[dict],
        scraped: list[dict],
    ) -> str:
        """合并搜索摘要和抓取内容为 LLM 输入"""
        parts = []

        # 搜索摘要
        parts.append("=== 搜索结果摘要 ===")
        for r in search_results:
            if isinstance(r, dict):
                parts.append(f"标题: {r.get('title', '')}\n摘要: {r.get('content', '')}\n")
            else:
                parts.append(f"(非 dict 类型的搜索结果: {type(r).__name__})\n")

        # 抓取内容
        for s in scraped:
            if isinstance(s, dict) and s.get("text") and not s.get("error"):
                parts.append(f"=== 页面内容: {s.get('title', '')} ===")
                parts.append(str(s.get("text", ""))[:3000])
                parts.append("")

        return "\n".join(parts)
