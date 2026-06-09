"""
撰写 Agent (Writer)

职责：
  1. 接收 Analyst 输出的 FeatureMatrix + MarketInsight[]
  2. 通过 LLM 生成执行摘要和战略建议
  3. 将全部章节合成为完整 Markdown 报告
  4. 保存到 outputs/ 目录
  5. 发送消息给 Reviewer 进入质检环节

继承自 BaseAgent。
"""

from datetime import datetime
from typing import Any, Optional

from loguru import logger

from agents.base import BaseAgent
from core.message_bus import MessageType
from core.schema import (
    CompetitorProfile,
    FeatureMatrix,
    MarketInsight,
    StructuredReport,
)
from models.report import ReportRenderer


# ============================================================
# LLM Prompt 模板
# ============================================================

SUMMARY_PROMPT = """你是一位资深的技术文档撰写专家。请根据以下竞品分析数据，撰写一份专业的执行摘要。

## 分析数据
{analysis_data}

## 要求
1. 长度：3-5 句话，约 150-250 字
2. 内容必须涵盖：分析范围、关键发现、核心结论
3. 语言专业简洁，面向产品决策者
4. 不要重复报告标题
5. 只输出摘要文本，不要加任何标记
"""

RECOMMENDATIONS_PROMPT = """你是一位资深的战略顾问。请根据以下竞品分析数据，提出 3-5 条战略建议。

## 分析数据
{analysis_data}

## 要求
1. 每条建议 1-2 句话，具体可操作
2. 基于数据中发现的差异化机会和威胁
3. 按优先级排序
4. 以 JSON 列表格式输出：["建议1", "建议2", "建议3"]
5. 只输出 JSON 列表
"""


# ============================================================
# Writer Agent
# ============================================================

class WriterAgent(BaseAgent):
    """撰写 Agent

    输入: state["competitor_profiles"] + state["feature_matrix"] + state["market_insights"]
    输出: state["report"]（Markdown 字符串）

    执行流程:
      1. 反序列化上游数据
      2. LLM 生成执行摘要
      3. LLM 生成战略建议
      4. 组装 StructuredReport
      5. 渲染 Markdown 并保存
      6. 发送消息给 Reviewer
    """

    def __init__(
        self,
        message_bus=None,
        llm=None,
        config: Optional[dict] = None,
        renderer: Optional[ReportRenderer] = None,
    ):
        super().__init__(
            name="writer",
            message_bus=message_bus,
            llm=llm,
            config=config,
        )
        self.renderer = renderer or ReportRenderer()

    def execute(self, state: dict, **kwargs) -> dict:
        """执行报告撰写流程

        Args:
            state: LangGraph AgentState

        Returns:
            更新后的 state 片段
        """
        raw_targets = state.get("target_products") or [state.get("target_product", "Unknown")]
        if isinstance(raw_targets, str):
            raw_targets = [raw_targets]
        targets = [t for t in raw_targets if isinstance(t, str) and len(t) >= 2]
        if not targets:
            targets = [state.get("target_product", "Unknown")]
        target = ", ".join(targets) if len(targets) <= 3 else f"{targets[0]} 等 {len(targets)} 个竞品"
        logger.info(f"[Writer] 开始撰写报告: {target}")

        # --- Step 1: 反序列化上游数据 ---
        profiles = self._deserialize_profiles(state.get("competitor_profiles", []))
        feature_matrix = self._deserialize_feature_matrix(state.get("feature_matrix"))
        market_insights = self._deserialize_insights(state.get("market_insights", []))

        if not profiles:
            raise ValueError("state 中缺少 competitor_profiles")

        # --- Step 2: 构建分析数据文本 ---
        analysis_data = self._build_analysis_text(profiles, feature_matrix, market_insights)

        # --- Step 3: 生成执行摘要 ---
        s_start = datetime.now()
        self._log_step(action="summary_generation", input_summary="LLM 生成执行摘要")

        if self.llm is None:
            names = ", ".join(p.name for p in profiles)
            category = profiles[0].category if profiles and profiles[0].category else "该品类"
            summary = (
                f"本报告对 **{names}** 进行了系统性的竞品分析，覆盖功能对比、SWOT 分析和市场定位三个维度。"
                f"由于 AI 模型未配置，当前报告内容为基于模拟数据的结构演示，"
                f"实际使用时请配置 LLM API Key 以获取完整的智能分析结果。"
            )
        else:
            summary = self._generate_summary(analysis_data)

        self._log_step(
            action="summary_generation",
            output_summary=summary[:100] + "...",
            started_at=s_start,
            duration_ms=(datetime.now() - s_start).total_seconds() * 1000,
        )

        # --- Step 4: 生成战略建议 ---
        r_start = datetime.now()
        self._log_step(action="recommendations_generation", input_summary="LLM 生成战略建议")

        if self.llm is None:
            recommendations = [
                f"配置 LLM API Key 以获取针对 {target} 的定制化战略建议",
                "在 config/settings.yaml 中调整分析维度以匹配你的行业需求",
            ]
        else:
            recommendations = self._generate_recommendations(analysis_data)

        self._log_step(
            action="recommendations_generation",
            output_summary=f"生成 {len(recommendations)} 条建议",
            started_at=r_start,
            duration_ms=(datetime.now() - r_start).total_seconds() * 1000,
        )

        # --- Step 5: 组装 StructuredReport ---
        self._log_step(action="report_assembly", input_summary="组装报告各章节")

        report = StructuredReport(
            title=f"{target} 竞品分析报告",
            executive_summary=summary,
            competitor_profiles=profiles,
            feature_matrix=feature_matrix,
            market_insights=market_insights,
            strategic_recommendations=recommendations,
            trace_id=state.get("trace_id", ""),
        )

        # --- Step 6: 渲染 Markdown 并保存 ---
        output_dir = self.config.get("storage", {}).get("outputs_dir", "./outputs") if self.config else "./outputs"
        filepath = self.renderer.save_report(report, output_dir=output_dir)
        markdown = self.renderer.render_full(report)

        self._log_step(
            action="report_saved",
            output_summary=f"报告已保存: {filepath} ({len(markdown)} 字符)",
        )

        # --- Step 7: 发送消息给 Reviewer ---
        self.send_message(
            receiver="reviewer",
            msg_type=MessageType.DATA_OUTPUT,
            payload={
                "target_product": target,
                "report_file": filepath,
                "report_length": len(markdown),
                "sections": 7,
            },
        )

        return {
            "report": markdown,
        }

    # ============================================================
    # 内部方法
    # ============================================================

    def _generate_summary(self, analysis_data: str) -> str:
        """LLM 生成执行摘要"""
        prompt = SUMMARY_PROMPT.format(analysis_data=analysis_data[:5000])
        return self._invoke_llm(prompt)

    def _generate_recommendations(self, analysis_data: str) -> list[str]:
        """LLM 生成战略建议"""
        import json
        import re

        prompt = RECOMMENDATIONS_PROMPT.format(analysis_data=analysis_data[:5000])
        response = self._invoke_llm(prompt)
        text = response.strip()
        # 解析 JSON 列表
        try:
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:])
                if text.endswith("```"):
                    text = text[:-3]
            return json.loads(text.strip())
        except (json.JSONDecodeError, ValueError):
            pass  # 不是纯 JSON，尝试正则提取

        match = re.search(r'\[.*?\]', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except (json.JSONDecodeError, ValueError):
                logger.warning(f"正则提取的非 JSON 内容: {match.group(0)[:100]}")
        return []  # 所有解析路径都失败时返回空列表

    @staticmethod
    def _build_analysis_text(
        profiles: list[CompetitorProfile],
        feature_matrix: Optional[FeatureMatrix],
        market_insights: list[MarketInsight],
    ) -> str:
        """构建 LLM 用的分析数据摘要"""
        parts = []
        parts.append("=== 竞品概览 ===")
        for p in profiles:
            parts.append(f"- {p.name} ({p.company}): {p.description}")
            if p.strengths:
                parts.append(f"  优势: {', '.join(s.content for s in p.strengths)}")
            if p.weaknesses:
                parts.append(f"  劣势: {', '.join(w.content for w in p.weaknesses)}")

        if feature_matrix:
            parts.append(f"\n=== 功能对比总结 ===\n{feature_matrix.summary}")

        for mi in market_insights:
            parts.append(f"\n=== {mi.competitor_name} 市场洞察 ===")
            parts.append(f"定位: {mi.market_position}")
            parts.append(f"SWOT 优势: {', '.join(mi.swot.strengths)}")
            parts.append(f"SWOT 劣势: {', '.join(mi.swot.weaknesses)}")

        return "\n".join(parts)

    @staticmethod
    def _deserialize_profiles(raw: list) -> list[CompetitorProfile]:
        result = []
        for item in raw:
            if isinstance(item, CompetitorProfile):
                result.append(item)
            elif isinstance(item, dict):
                result.append(CompetitorProfile(**item))
        return result

    @staticmethod
    def _deserialize_feature_matrix(raw) -> Optional[FeatureMatrix]:
        if raw is None:
            return None
        if isinstance(raw, FeatureMatrix):
            return raw
        if isinstance(raw, dict):
            return FeatureMatrix(**raw)
        return None

    @staticmethod
    def _deserialize_insights(raw: list) -> list[MarketInsight]:
        result = []
        for item in raw:
            if isinstance(item, MarketInsight):
                result.append(item)
            elif isinstance(item, dict):
                result.append(MarketInsight(**item))
        return result
