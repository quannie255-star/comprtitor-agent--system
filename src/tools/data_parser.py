"""
数据结构化解析器

将搜索和抓取的原始文本通过 LLM 转换为结构化的 CompetitorProfile。
这是采集 Agent 的最后一个环节：非结构化数据 → Schema 化输出。
"""

import json
from datetime import datetime
from typing import Any

from loguru import logger

from core.schema import AnnotatedFinding, CompetitorProfile, Evidence, Feature, Pricing

# ============================================================
# 解析提示词模板
# ============================================================

EXTRACT_PROMPT = """你是一个专业的竞品信息提取助手。请从以下原始信息中提取结构化数据。

## 目标产品
{target_product}

## 原始信息
{raw_text}

## 输出要求
请以 JSON 格式输出，严格遵循以下 Schema（只输出 JSON，不要加任何解释）：

```json
{{
  "name": "产品名称",
  "company": "所属公司",
  "website": "官网地址",
  "category": "产品分类（如：协作知识库、项目管理、CRM等）",
  "description": "产品简介（1-3句话）",
  "target_market": "目标市场/用户群",
  "core_features": [
    {{"name": "功能名", "description": "功能描述", "supported": true, "notes": ""}}
  ],
  "pricing": {{
    "model": "订阅制/免费增值/买断/按量付费",
    "starting_price": "起售价",
    "details": "定价详情"
  }},
  "strengths": ["优势1", "优势2"],
  "weaknesses": ["劣势1", "劣势2"]
}}
```

## 重要规则
1. 无法从原文确认的字段填 "待确认"
2. strengths 和 weaknesses 必须是原文中实际提到的，不要编造
3. core_features 只提取原文明确列出的功能
4. 只输出 JSON，不要加 Markdown 代码块标记
"""


# ============================================================
# 解析器
# ============================================================

class DataParser:
    """数据结构化解析器

    将 LLM 调用委托给 Collector Agent（其持有 LLM 实例）。
    此工具负责 Prompt 构建和 JSON 解析。

    使用方式：
        parser = DataParser()
        result = parser.parse_with_llm(
            llm=agent.llm,
            target_product="Notion",
            raw_text="...",
            source_url="https://...",
            source_title="...",
        )
    """

    @staticmethod
    def build_prompt(target_product: str, raw_text: str) -> str:
        """构建提取 Prompt"""
        return EXTRACT_PROMPT.format(
            target_product=target_product,
            raw_text=raw_text[:8000],  # 截断过长文本
        )

    @staticmethod
    def parse_json_response(response_text: str) -> dict:
        """解析 LLM 返回的 JSON 字符串

        Args:
            response_text: LLM 原始输出

        Returns:
            解析后的 dict

        Raises:
            ValueError: JSON 解析失败
        """
        text = response_text.strip()
        # 去除可能的 Markdown 代码块标记
        if text.startswith("```"):
            # 找到第一个换行符后的内容，去掉末尾的 ```
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试提取 JSON 片段
            import re
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            raise ValueError(f"无法从 LLM 回复中解析 JSON: {text[:200]}...")

    def parse_to_profile(
        self,
        llm: Any,
        target_product: str,
        raw_text: str,
        source_url: str,
        source_title: str,
    ) -> CompetitorProfile:
        """执行完整解析流程：LLM 提取 → CompetitorProfile

        Args:
            llm: LangChain ChatModel 实例
            target_product: 待分析的产品名称
            raw_text: 原始文本（搜索摘要 + 抓取内容）
            source_url: 数据来源 URL
            source_title: 数据来源标题

        Returns:
            CompetitorProfile 实例
        """
        logger.info(f"开始解析: {target_product} (来源: {source_title})")

        # 1. 构建证据
        evidence = Evidence(
            source_id=f"src_{hash(source_url) % 100000:05d}",
            source_url=source_url,
            source_title=source_title,
            excerpt=raw_text[:500],
            retrieved_at=datetime.now(),
            confidence=0.85,
        )

        # 2. 调用 LLM 提取结构化数据
        if llm is None:
            logger.warning("LLM 未配置，返回 None — 由 Collector 构建降级 Profile")
            return None

        prompt = self.build_prompt(target_product, raw_text)
        try:
            response = llm.invoke(prompt)
            raw_json = self.parse_json_response(
                response.content if hasattr(response, 'content') else str(response)
            )
        except Exception as e:
            logger.error(f"LLM 解析失败: {e}")
            return None

        # 3. 构建 CompetitorProfile
        # 防御：LLM 可能返回 JSON 数组而非对象
        if not isinstance(raw_json, dict):
            logger.warning(f"LLM 返回了 {type(raw_json).__name__} 而非 dict，回退")
            return None

        features = [
            Feature(
                name=f.get("name", ""),
                description=f.get("description", ""),
                supported=f.get("supported", True),
                notes=f.get("notes", ""),
                evidence=evidence,
            )
            for f in raw_json.get("core_features", [])
        ]

        pricing_data = raw_json.get("pricing", {})
        pricing = Pricing(
            model=pricing_data.get("model", "待确认"),
            starting_price=pricing_data.get("starting_price", "待确认"),
            details=pricing_data.get("details", ""),
            source=evidence,
        ) if pricing_data else None

        strengths = [
            AnnotatedFinding(content=s, evidence=evidence)
            for s in raw_json.get("strengths", [])
        ]
        weaknesses = [
            AnnotatedFinding(content=w, evidence=evidence)
            for w in raw_json.get("weaknesses", [])
        ]

        profile = CompetitorProfile(
            name=raw_json.get("name", target_product),
            company=raw_json.get("company", "待确认"),
            website=raw_json.get("website", source_url),
            category=raw_json.get("category", "待确认"),
            description=raw_json.get("description", "待确认"),
            target_market=raw_json.get("target_market", "待确认"),
            core_features=features,
            pricing=pricing,
            strengths=strengths,
            weaknesses=weaknesses,
            data_sources=[evidence],
        )

        logger.info(f"解析完成: {target_product} → {len(features)} 功能, "
                     f"{len(strengths)} 优势, {len(weaknesses)} 劣势")
        return profile

    @staticmethod
    def _minimal_profile(target_product: str, evidence: Evidence) -> CompetitorProfile:
        """生成最小化 Profile（LLM 不可用时的降级方案）"""
        return CompetitorProfile(
            name=target_product,
            company="待确认",
            description="待确认（LLM 未配置）",
            data_sources=[evidence],
        )
