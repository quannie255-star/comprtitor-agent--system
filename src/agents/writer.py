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

from loguru import logger

from agents.base import BaseAgent
from core.message_bus import MessageType
from core.schema import (
    CompetitorProfile,
    DORAMetrics,
    FeatureMatrix,
    MarketInsight,
    Priority,
    PullRequest,
    ReviewIssue,
    ReviewReport,
    ReviewScore,
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
        config: dict | None = None,
        renderer: ReportRenderer | None = None,
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

        # --- 输入类型检测：代码审查模式 ---
        review_issues = state.get("review_issues")
        review_score = state.get("review_score")
        pr_data = state.get("pr_data")
        if review_issues is not None and pr_data:
            return self._execute_review_report(pr_data, review_issues, review_score, state)

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

        # --- Step 3-4: 生成摘要 + 建议（合并为 1 次 LLM 调用）---
        w_start = datetime.now()
        self._log_step(action="content_generation", input_summary="LLM 生成摘要 + 建议")

        if self.llm is None:
            names = ", ".join(p.name for p in profiles)
            summary = (
                f"本报告对 **{names}** 进行了系统性的竞品分析，覆盖功能对比、SWOT 分析和市场定位。"
                f"由于 AI 模型未配置，当前内容为结构演示，实际使用时请配置 LLM API Key。"
            )
            recommendations = [
                "配置 LLM API Key 以获取定制化建议",
                "在 config/settings.yaml 中调整分析维度",
            ]
        else:
            # 合并 prompt：摘要 + 建议一起返回，用 ===RECS=== 分隔
            combined = (
                SUMMARY_PROMPT.format(analysis_data=analysis_data[:4000])
                + "\n\n---\n\n"
                + RECOMMENDATIONS_PROMPT.format(analysis_data=analysis_data[:4000])
                + "\n\n请用 ===RECS=== 分隔符分开输出摘要和建议。先输出摘要，然后 ===RECS===，然后 JSON 列表。"
            )
            response = self._invoke_llm(combined)

            # 分离摘要和建议
            if "===RECS===" in response:
                summary, recs_text = response.split("===RECS===", 1)
                summary = summary.strip()
                recommendations = self._parse_json_list(recs_text)
            else:
                summary = response[:500]
                recommendations = ["基于现有数据制定差异化策略"]

        self._log_step(
            action="content_generation",
            output_summary=f"摘要 {len(summary)} 字, {len(recommendations)} 条建议",
            started_at=w_start,
            duration_ms=(datetime.now() - w_start).total_seconds() * 1000,
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

    @staticmethod
    def _parse_json_list(text: str) -> list[str]:
        """从 LLM 输出中提取 JSON 列表（建议）"""
        import json, re
        text = text.strip()
        # 移除代码块
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
        try:
            return json.loads(text.strip())
        except (json.JSONDecodeError, ValueError):
            match = re.search(r'\[.*?\]', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except (json.JSONDecodeError, ValueError):
                    pass
            return [text.strip()[:200]] if text.strip() else ["基于现有数据制定差异化策略"]

    def _generate_summary(self, analysis_data: str) -> str:
        """LLM 生成执行摘要（已合并，保留兼容）"""
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
        feature_matrix: FeatureMatrix | None,
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
    def _deserialize_feature_matrix(raw) -> FeatureMatrix | None:
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

    # ============================================================
    # Product Line 2: 代码审查报告
    # ============================================================

    def write_review_report(self, report: ReviewReport) -> str:
        """生成完整的 8 章节 Markdown 审查报告

        Args:
            report: 完整的 ReviewReport 对象（含 PR、issues、score）

        Returns:
            完整的 Markdown 报告字符串
        """
        logger.info(f"[Writer:Code] 生成代码审查报告: {report.pr.title}")
        return report.render_markdown()

    def _format_issues_for_report(self, issues: list[ReviewIssue]) -> str:
        """按优先级和分类格式化问题列表"""
        if not issues:
            return "_No issues found. Great job!_"

        lines = []
        # 按优先级分组
        for pri in Priority:
            pri_issues = [i for i in issues if i.priority == pri]
            if not pri_issues:
                continue
            icon = {"P0": "🔴", "P1": "🟠", "P2": "🟡", "P3": "🟢"}.get(pri.value, "⚪")
            lines.append(f"### {icon} {pri.value} — {len(pri_issues)} issues")
            lines.append("")
            for issue in pri_issues:
                lines.append(f"**{issue.title}**  `[{issue.category.value}]`")
                if issue.file_path:
                    loc = f"`{issue.file_path}`"
                    if issue.line_number:
                        loc += f":{issue.line_number}"
                    lines.append(f"- Location: {loc}")
                lines.append(f"- Source: `{issue.agent_source.value}` (confidence: {issue.confidence:.0%})")
                if issue.description:
                    lines.append(f"- {issue.description}")
                if issue.suggested_fix:
                    lines.append(f"- Fix: {issue.suggested_fix}")
                lines.append("")
        return "\n".join(lines)

    def _execute_review_report(
        self, pr_data: dict, issues_data: list, score_data: dict, state: dict,
    ) -> dict:
        """执行代码审查报告生成（Product Line 2 入口）

        输入: state["pr_data"] + state["review_issues"] + state["review_score"]
        输出: state["report"]
        """
        logger.info("[Writer:Code] 开始生成代码审查报告")

        pr = PullRequest(**pr_data) if isinstance(pr_data, dict) else pr_data
        issues = [
            ReviewIssue(**i) if isinstance(i, dict) else i
            for i in (issues_data or [])
        ]
        score = ReviewScore(**score_data) if isinstance(score_data, dict) else (score_data or ReviewScore())

        # 质量门禁判定
        gate_passed, gate_failures = score.passes_quality_gate()
        critical = sum(1 for i in issues if i.priority == Priority.P0_CRITICAL)
        high = sum(1 for i in issues if i.priority == Priority.P1_HIGH)

        if not gate_passed and critical == 0:
            # 无 critical issue 但分数不够 → 仍可标记为需要改进
            pass

        # 构建 ReviewReport
        selected = state.get("selected_agents") or []
        from core.schema import AgentType
        agents = []
        for a in selected:
            try:
                agents.append(AgentType(a) if isinstance(a, str) else a)
            except ValueError:
                pass

        report = ReviewReport(
            pr=pr,
            issues=issues,
            score=score,
            selected_agents=agents or [AgentType.CLAUDE, AgentType.CODEX],
            quality_gate_passed=gate_passed,
            quality_gate_failures=gate_failures,
            trace_id=state.get("trace_id", ""),
        )

        markdown = self.write_review_report(report)

        # 保存到 outputs/
        output_dir = self.config.get("storage", {}).get("outputs_dir", "./outputs") if self.config else "./outputs"
        import os
        os.makedirs(output_dir, exist_ok=True)
        safe_title = pr.title[:50].replace(" ", "_").replace("/", "_")
        filepath = f"{output_dir}/review_{safe_title}_{report.id}.md"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(markdown)

        self._log_step(
            action="review_report_generated",
            output_summary=f"报告 {len(markdown)} 字符, gate={'PASSED' if gate_passed else 'FAILED'}",
        )

        self.send_message(
            receiver="reviewer",
            msg_type=MessageType.DATA_OUTPUT,
            payload={
                "mode": "code_review",
                "pr_title": pr.title,
                "report_file": filepath,
                "quality_gate_passed": gate_passed,
            },
        )

        return {"report": markdown}
