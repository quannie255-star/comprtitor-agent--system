"""
分析 Agent (Analyst)

职责：
  1. 接收 Collector 输出的 CompetitorProfile
  2. 执行 SWOT 分析、功能对比、市场定位、差异化洞察
  3. 输出 FeatureMatrix + MarketInsight
  4. 每条结论绑定 Evidence（字段级溯源）

继承自 BaseAgent，通过消息总线接收上游数据、发送分析结果给下游。
"""

from datetime import datetime
from typing import Any, Optional

from loguru import logger

from agents.base import BaseAgent
from core.message_bus import MessageType
from core.schema import CompetitorProfile, Evidence, FeatureMatrix, MarketInsight, SWOTItem
from models.feature import DEFAULT_DIMENSIONS, FeatureAnalyzer, FEATURE_COMPARISON_PROMPT
from models.market import MarketInsightBuilder, MARKET_INSIGHT_PROMPT


class AnalystAgent(BaseAgent):
    """分析 Agent

    输入: state["competitor_profiles"]
    输出: state["feature_matrix"] + state["market_insights"]

    执行流程:
      1. 反序列化 CompetitorProfile
      2. LLM 功能对比分析 → FeatureMatrix
      3. LLM 市场洞察分析 → MarketInsight
      4. 汇总结果，发送消息给 Writer
    """

    def __init__(
        self,
        message_bus=None,
        llm=None,
        config: Optional[dict] = None,
    ):
        super().__init__(
            name="analyst",
            message_bus=message_bus,
            llm=llm,
            config=config,
        )
        self.feature_analyzer = FeatureAnalyzer()
        self.market_builder = MarketInsightBuilder()

        # 从 config 读取分析维度
        agent_config = config.get("agents", {}).get("analyst", {}) if config else {}
        self.dimensions = agent_config.get("comparison_dimensions", DEFAULT_DIMENSIONS)

    def execute(self, state: dict, **kwargs) -> dict:
        """执行分析流程

        Args:
            state: LangGraph AgentState

        Returns:
            更新后的 state 片段
        """
        # --- Step 1: 获取竞品数据 ---
        competitor_data = state.get("competitor_profiles", [])
        if not competitor_data:
            raise ValueError("state 中缺少 competitor_profiles，请先运行 CollectorAgent")

        # 反序列化
        profiles = [
            p if isinstance(p, CompetitorProfile) else CompetitorProfile(**p)
            for p in competitor_data
        ]
        targets = state.get("target_products") or [state.get("target_product", "")]
        # 防御：确保是字符串，且不是被错误迭代的字符
        if isinstance(targets, str):
            targets = [targets]
        target = targets[0] if targets else profiles[0].name
        if len(target) < 2:
            logger.warning(f"⚠ 竞品名可能被截断: '{target}' | state.target_product='{state.get('target_product', 'N/A')}' | state.target_products={state.get('target_products', 'N/A')}")
        source_pool_raw = state.get("source_pool", [])
        evidence_list = [
            e if isinstance(e, Evidence) else Evidence(**e)
            for e in source_pool_raw
        ]

        logger.info(f"[Analyst] 开始分析: {target} ({len(profiles)} 个竞品: {[p.name for p in profiles]})")

        # --- Step 2: 功能对比分析 ---
        f_start = datetime.now()
        self._log_step(
            action="feature_analysis_start",
            input_summary=f"分析 {len(profiles)} 个竞品, {len(self.dimensions)} 个维度",
        )

        comparison_text = self.feature_analyzer.build_comparison_data(profiles)
        competitor_names = [
            p.name for p in profiles
            if p.name and p.name != "待确认"
        ][:3]  # 过滤无效 + 上限 3
        competitor_list_str = "\n".join(f"- {n}" for n in competitor_names)
        prompt = FEATURE_COMPARISON_PROMPT.format(
            competitor_data=comparison_text,
            dimensions=", ".join(self.dimensions),
        )
        # 多竞品时，在 prompt 前插入竞品清单，强制 LLM 输出完整矩阵
        if len(competitor_names) > 1:
            prompt = (
                f"## ⚠️ 重要：本次需要对比 {len(competitor_names)} 个竞品\n"
                f"请在 matrix 的每个维度中为以下所有竞品填写评价：\n"
                f"{competitor_list_str}\n\n"
                + prompt
            )
        llm_output = self._invoke_llm(prompt)

        competitor_names = [p.name for p in profiles]

        # 无 LLM 时返回默认矩阵，避免 JSON 解析占位符崩溃
        if self.llm is None:
            feature_matrix = FeatureMatrix(
                competitors=competitor_names,
                dimensions=self.dimensions,
                matrix={dim: {name: "待 LLM 分析" for name in competitor_names} for dim in self.dimensions},
                summary=f"{target} 功能对比（LLM 未配置，需人工补充）",
                evidence_list=evidence_list,
            )
        else:
            feature_matrix = self.feature_analyzer.build_matrix_from_llm(
                llm_output,
                competitors=competitor_names,
                dimensions=self.dimensions,
                evidence_list=evidence_list,
            )

        self._log_step(
            action="feature_analysis_complete",
            output_summary=f"矩阵维度: {len(feature_matrix.dimensions)}, "
                           f"对比总结: {feature_matrix.summary[:100]}...",
            evidence_refs=[e.source_id for e in evidence_list],
            started_at=f_start,
            duration_ms=(datetime.now() - f_start).total_seconds() * 1000,
        )

        # --- Step 3: 市场洞察分析 ---
        m_start = datetime.now()
        self._log_step(
            action="market_insight_start",
            input_summary=f"分析 {target} 的市场定位",
        )

        # 对每个竞品画像生成洞察
        market_insights = []
        for profile in profiles:
            context = self.market_builder.build_context(profile)
            insight_prompt = MARKET_INSIGHT_PROMPT.format(
                competitor_data=comparison_text,
                industry_context=context,
            )
            if self.llm is None:
                insight = MarketInsight(
                    competitor_name=profile.name,
                    swot=SWOTItem(
                        strengths=["待 LLM 分析"],
                        weaknesses=["待 LLM 分析"],
                        opportunities=["待 LLM 分析"],
                        threats=["待 LLM 分析"],
                    ),
                    market_position="待 LLM 分析",
                    evidence_list=evidence_list,
                )
            else:
                insight_output = self._invoke_llm(insight_prompt)
                insight = self.market_builder.from_llm_response(
                    insight_output,
                    competitor_name=profile.name,
                    evidence_list=evidence_list,
                )
            market_insights.append(insight)

        self._log_step(
            action="market_insight_complete",
            output_summary=f"生成 {len(market_insights)} 条市场洞察",
            evidence_refs=[e.source_id for e in evidence_list],
            started_at=m_start,
            duration_ms=(datetime.now() - m_start).total_seconds() * 1000,
        )

        # --- Step 4: 发送消息给 Writer ---
        self.send_message(
            receiver="writer",
            msg_type=MessageType.DATA_OUTPUT,
            payload={
                "target_product": target,
                "feature_matrix": feature_matrix.model_dump(mode="json"),
                "market_insights_count": len(market_insights),
            },
        )

        return {
            "feature_matrix": feature_matrix.model_dump(mode="json"),
            "market_insights": [mi.model_dump(mode="json") for mi in market_insights],
        }
