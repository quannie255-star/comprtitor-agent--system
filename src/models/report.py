"""
竞品报告渲染器

将 StructuredReport 渲染为带证据引用的 Markdown 报告，
并持久化到 outputs/ 目录。
"""

import os

from core.schema import (
    CompetitorProfile,
    FeatureMatrix,
    MarketInsight,
    ReviewResult,
    StructuredReport,
)


class ReportRenderer:
    """Markdown 报告渲染器

    职责：
      - 将 StructuredReport 的各组件渲染为 Markdown 章节
      - 自动生成证据引用标记 [source_id]
      - 报告末尾汇总参考来源列表
    """

    # ============================================================
    # 章节渲染
    # ============================================================

    @staticmethod
    def render_header(report: StructuredReport) -> str:
        """报告头部"""
        lines = [
            f"# {report.title}",
            "",
            f"> 生成时间: {report.generated_at.strftime('%Y-%m-%d %H:%M')}",
            f"> 追踪 ID: `{report.trace_id}`",
            "",
            "---",
            "",
        ]
        return "\n".join(lines)

    @staticmethod
    def render_executive_summary(report: StructuredReport) -> str:
        """执行摘要"""
        lines = [
            "## 一、执行摘要",
            "",
            report.executive_summary,
            "",
        ]
        return "\n".join(lines)

    @staticmethod
    def render_competitor_overview(profiles: list[CompetitorProfile]) -> str:
        """竞品概览"""
        lines = ["## 二、竞品概览", ""]
        for i, p in enumerate(profiles, 1):
            lines.append(f"### 2.{i} {p.name} ({p.company})")
            lines.append("")
            lines.append("| 属性 | 信息 |")
            lines.append("|------|------|")
            lines.append(f"| 官网 | {p.website} |")
            lines.append(f"| 分类 | {p.category} |")
            lines.append(f"| 目标市场 | {p.target_market} |")
            lines.append(f"| 简介 | {p.description} |")
            if p.pricing:
                lines.append(f"| 定价模式 | {p.pricing.model} |")
                lines.append(f"| 起售价 | {p.pricing.starting_price} |")
            lines.append("")

            # 核心功能
            if p.core_features:
                lines.append("**核心功能**:")
                for f in p.core_features:
                    evidence_ref = f" `[{f.evidence.source_id}]`" if f.evidence else ""
                    status = "✅" if f.supported else "❌"
                    lines.append(f"- {status} **{f.name}**: {f.description}{evidence_ref}")
                lines.append("")

            # 优势
            if p.strengths:
                lines.append("**优势**:")
                for s in p.strengths:
                    lines.append(f"- {s.content} `[{s.evidence.source_id}]`")
                lines.append("")

            # 劣势
            if p.weaknesses:
                lines.append("**劣势**:")
                for w in p.weaknesses:
                    lines.append(f"- {w.content} `[{w.evidence.source_id}]`")
                lines.append("")

        return "\n".join(lines)

    @staticmethod
    def render_feature_matrix(fm: FeatureMatrix | None) -> str:
        """功能对比矩阵 → Markdown 表格"""
        if fm is None:
            return "## 三、功能对比\n\n*暂无功能对比数据*\n\n"

        lines = ["## 三、功能对比矩阵", "", f"**对比总结**: {fm.summary}", ""]

        # 表头
        header = ["维度"] + fm.competitors
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "|".join(["------"] * len(header)) + "|")

        # 数据行
        for dim in fm.dimensions:
            row = [dim]
            for comp in fm.competitors:
                row.append(fm.matrix.get(dim, {}).get(comp, "N/A"))
            lines.append("| " + " | ".join(row) + " |")

        # 证据引用
        if fm.evidence_list:
            refs = ", ".join(f"`[{e.source_id}]`" for e in fm.evidence_list)
            lines.extend(["", f"*数据来源: {refs}*"])

        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def render_market_insights(insights: list[MarketInsight]) -> str:
        """市场洞察 → SWOT + 趋势"""
        lines = ["## 四、市场洞察", ""]

        for i, mi in enumerate(insights, 1):
            lines.append(f"### 4.{i} {mi.competitor_name}")
            lines.append(f"**市场定位**: {mi.market_position}")
            lines.append("")

            # SWOT 表格
            swot = mi.swot
            lines.append("**SWOT 分析**:")
            lines.append("")
            lines.append("| 维度 | 内容 |")
            lines.append("|------|------|")
            for item in swot.strengths:
                lines.append(f"| 💪 优势 | {item} |")
            for item in swot.weaknesses:
                lines.append(f"| ⚠️ 劣势 | {item} |")
            for item in swot.opportunities:
                lines.append(f"| 🚀 机会 | {item} |")
            for item in swot.threats:
                lines.append(f"| ⚡ 威胁 | {item} |")
            lines.append("")

            # 差异化
            if mi.differentiation_points:
                lines.append("**差异化优势**:")
                for d in mi.differentiation_points:
                    lines.append(f"- {d.content} `[{d.evidence.source_id}]`")
                lines.append("")

            # 趋势
            if mi.trends:
                lines.append("**趋势洞察**:")
                for t in mi.trends:
                    lines.append(f"- {t.content} `[{t.evidence.source_id}]`")
                lines.append("")

        return "\n".join(lines)

    @staticmethod
    def render_recommendations(recommendations: list[str]) -> str:
        """战略建议"""
        if not recommendations:
            return ""
        lines = ["## 五、战略建议", ""]
        for i, rec in enumerate(recommendations, 1):
            lines.append(f"{i}. {rec}")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def render_references(profiles: list[CompetitorProfile]) -> str:
        """参考来源汇总"""
        lines = ["## 六、参考来源", ""]
        seen = set()
        count = 1
        for p in profiles:
            for src in p.data_sources:
                if src.source_id not in seen:
                    seen.add(src.source_id)
                    lines.append(
                        f"{count}. `[{src.source_id}]` [{src.source_title}]({src.source_url}) "
                        f"（置信度: {src.confidence:.0%}）"
                    )
                    count += 1
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def render_review_section(review: ReviewResult | None) -> str:
        """质检结论章节"""
        if review is None:
            return ""
        status = "✅ 通过" if review.passed else "❌ 未通过"
        lines = [
            "## 七、质检结论",
            "",
            f"**状态**: {status}",
            f"**评分**: {review.score:.0%}",
            f"**审查时间**: {review.reviewed_at.strftime('%Y-%m-%d %H:%M')}",
            "",
        ]
        if review.issues:
            lines.append("**发现的问题**:")
            for issue in review.issues:
                lines.append(f"- ⚠️ {issue}")
            lines.append("")
        if review.suggestions:
            lines.append("**修正建议**:")
            for sug in review.suggestions:
                lines.append(f"- 💡 {sug}")
            lines.append("")
        return "\n".join(lines)

    # ============================================================
    # 完整渲染 & 保存
    # ============================================================

    def render_full(self, report: StructuredReport) -> str:
        """渲染完整 Markdown 报告"""
        sections = [
            self.render_header(report),
            self.render_executive_summary(report),
            self.render_competitor_overview(report.competitor_profiles),
            self.render_feature_matrix(report.feature_matrix),
            self.render_market_insights(report.market_insights),
            self.render_recommendations(report.strategic_recommendations),
            self.render_review_section(report.review_result),
            self.render_references(report.competitor_profiles),
        ]
        return "\n".join(sections)

    def save_report(
        self,
        report: StructuredReport,
        output_dir: str = "./outputs",
    ) -> str:
        """渲染并保存报告到文件

        Args:
            report: 结构化报告
            output_dir: 输出目录

        Returns:
            保存的文件路径
        """
        os.makedirs(output_dir, exist_ok=True)
        filename = f"report_{report.generated_at.strftime('%Y%m%d_%H%M%S')}_{report.trace_id[:8]}.md"
        filepath = os.path.join(output_dir, filename)

        markdown = self.render_full(report)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(markdown)

        return filepath
