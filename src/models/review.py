"""
质检审查工具集

提供事实核查、一致性校验、溯源完整性检查等质检能力。
与 schema.py 中的 ReviewResult + RejectReason 配合使用。
"""

from core.schema import (
    CompetitorProfile,
    FeatureMatrix,
    RejectReason,
    ReviewResult,
    StructuredReport,
)

# ============================================================
# 质检 Prompt 模板
# ============================================================

REVIEW_PROMPT = """你是一位严谨的报告质量审核专家。请对以下竞品分析报告进行交叉审查。

## 报告内容
{report_content}

## 上游原始数据（用于事实核查）
{upstream_data}

## 审查维度
1. **事实准确性**：报告中的每条论断是否可追溯到原始数据？有无凭空编造的断言？
2. **逻辑一致性**：前后章节是否存在矛盾？（如：SWOT 说优势是"价格低"，功能对比却说"定价偏高"）
3. **完整性**：SWOT 分析、功能对比、市场洞察等章节是否齐全？有无缺失的关键维度？
4. **证据置信度**：引用的数据来源是否可靠？置信度评分是否合理？

## 输出要求
请以 JSON 格式输出审查结果（只输出 JSON）：

```json
{{
  "passed": true/false,
  "reject_reason": "passed/insufficient_source/schema_mismatch/quality_issue",
  "score": 0.0-1.0,
  "issues": ["具体问题1", "具体问题2"],
  "suggestions": ["修正建议1", "修正建议2"],
  "missing_fields": ["缺失字段名1"]
}}
```

## 判定规则
- reject_reason="insufficient_source": 报告中大量引用缺乏原始数据支撑 → 需回 Collector 补充信源
- reject_reason="schema_mismatch": SWOT/功能对比等结构化数据缺失 → 需回 Analyst 补充分析
- reject_reason="quality_issue": 报告存在逻辑矛盾、格式错误或语句不通 → 需回 Writer 修正
- reject_reason="passed": 所有检查通过，报告可直接使用
- score >= 0.8 且 passed=true 才算高质量报告

## 重要
1. 只输出 JSON，不要加任何解释
2. issues 必须是具体可定位的问题，不要笼统描述
3. 宁可严格也不要放过隐患
"""


# ============================================================
# 质检工具
# ============================================================

class ReviewChecker:
    """质检审查器

    提供编程化的质检辅助方法，与 LLM 驱动的审查互补。
    """

    @staticmethod
    def check_evidence_completeness(profiles: list[CompetitorProfile]) -> list[str]:
        """检查竞品画像的证据完整性"""
        issues = []
        for p in profiles:
            if not p.data_sources:
                issues.append(f"{p.name}: 缺少数据来源（data_sources 为空）")
            if not p.strengths:
                issues.append(f"{p.name}: strengths 为空")
            if not p.weaknesses:
                issues.append(f"{p.name}: weaknesses 为空")
            if not p.core_features:
                issues.append(f"{p.name}: core_features 为空")
            for s in p.strengths:
                if not s.evidence:
                    issues.append(f"{p.name} 优势'{s.content}'缺少证据绑定")
            for w in p.weaknesses:
                if not w.evidence:
                    issues.append(f"{p.name} 劣势'{w.content}'缺少证据绑定")
        return issues

    @staticmethod
    def check_matrix_completeness(
        matrix: FeatureMatrix,
        profiles: list[CompetitorProfile],
    ) -> list[str]:
        """检查功能对比矩阵的完整性"""
        issues = []
        expected_competitors = {p.name for p in profiles}
        actual_competitors = set(matrix.competitors)
        if expected_competitors != actual_competitors:
            issues.append(
                f"矩阵竞品不匹配: 期望 {expected_competitors}, 实际 {actual_competitors}"
            )
        if not matrix.dimensions:
            issues.append("对比维度为空")
        if not matrix.matrix:
            issues.append("对比矩阵数据为空")
        if not matrix.summary:
            issues.append("缺少对比总结")
        return issues

    @staticmethod
    def check_report_completeness(report: StructuredReport) -> list[str]:
        """检查报告结构的完整性"""
        issues = []
        if not report.executive_summary:
            issues.append("缺少执行摘要")
        if not report.competitor_profiles:
            issues.append("缺少竞品画像")
        if not report.market_insights:
            issues.append("缺少市场洞察")
        if not report.strategic_recommendations:
            issues.append("缺少战略建议")
        return issues

    @staticmethod
    def evaluate_confidence(profiles: list[CompetitorProfile]) -> float:
        """计算数据源的平均置信度"""
        all_confidences = []
        for p in profiles:
            for src in p.data_sources:
                all_confidences.append(src.confidence)
        if not all_confidences:
            return 0.0
        return sum(all_confidences) / len(all_confidences)

    @staticmethod
    def make_review_result(
        passed: bool,
        reject_reason: RejectReason,
        score: float,
        issues: list[str],
        suggestions: list[str],
        missing_fields: list[str],
    ) -> ReviewResult:
        """构建 ReviewResult"""
        return ReviewResult(
            passed=passed,
            reject_reason=reject_reason,
            score=score,
            issues=issues,
            suggestions=suggestions,
            missing_fields=missing_fields,
        )
