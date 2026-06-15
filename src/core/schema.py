"""
竞品知识 Schema 定义

所有 Agent 共享的统一数据结构，基于 Pydantic V2。
设计原则：
  - 核心字段采用 AnnotatedFinding 实现字段级溯源
  - ReviewResult 含 RejectReason 枚举，支撑 LangGraph 条件路由
  - 所有 URL 字段统一为 str，避免 Pydantic V2 Url 对象序列化异常
  - AgentState TypedDict 作为 LangGraph 全局状态
"""

import operator
from datetime import datetime
from enum import Enum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

# ============================================================
# 基础原子类型
# ============================================================

class Evidence(BaseModel):
    """证据条目 — 每条分析结论必须绑定至少一条证据"""

    source_id: str = Field(description="全局唯一信源ID，如 src_001")
    source_url: str = Field(description="证据来源 URL（纯字符串，避免 pydantic_core.Url 序列化异常）")
    source_title: str = Field(description="来源标题/名称")
    excerpt: str = Field(description="关键原文摘录")
    retrieved_at: datetime = Field(default_factory=datetime.now, description="采集时间")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="证据置信度 0-1")


class AnnotatedFinding(BaseModel):
    """带证据标注的发现 — 用于 strengths/weaknesses 等字段的字段级溯源"""

    content: str = Field(description="发现/结论内容")
    evidence: Evidence = Field(description="支撑该发现的证据")


class Feature(BaseModel):
    """单个功能点"""

    name: str = Field(description="功能名称")
    description: str = Field(default="", description="功能描述")
    supported: bool = Field(default=True, description="该竞品是否支持此功能")
    notes: str = Field(default="", description="补充说明")
    evidence: Evidence | None = Field(default=None, description="功能信息来源")


class Pricing(BaseModel):
    """定价信息"""

    model: str = Field(description="定价模式：免费/订阅/买断/按量")
    starting_price: str = Field(default="", description="起售价")
    details: str = Field(default="", description="定价详情")
    source: Evidence | None = Field(default=None, description="定价信息来源")


# ============================================================
# 质检枚举与模型
# ============================================================

class RejectReason(str, Enum):
    """Reviewer 回退原因枚举 — 用于 LangGraph 条件路由"""

    INSUFFICIENT_SOURCE = "insufficient_source"   # 信源不足 → 回 Collector
    SCHEMA_MISMATCH = "schema_mismatch"            # Schema 缺失 → 回 Analyst
    QUALITY_ISSUE = "quality_issue"                # 质量问题 → 回 Writer
    PASSED = "passed"                              # 通过


class ReviewResult(BaseModel):
    """质检结论 — 质检 Agent 输出，决定 DAG 条件路由走向"""

    passed: bool = Field(description="是否通过质检")
    reject_reason: RejectReason = Field(
        default=RejectReason.PASSED, description="回退原因（passed 表示无需回退）"
    )
    score: float = Field(default=0.0, ge=0.0, le=1.0, description="质量评分 0-1")
    issues: list[str] = Field(default_factory=list, description="发现的问题列表")
    suggestions: list[str] = Field(default_factory=list, description="修正建议")
    missing_fields: list[str] = Field(default_factory=list, description="Schema 缺失字段名")
    reviewed_at: datetime = Field(default_factory=datetime.now, description="审查时间")


# ============================================================
# Agent 产出模型
# ============================================================

class CompetitorProfile(BaseModel):
    """竞品画像 — 采集 Agent 的主输出"""

    id: UUID = Field(default_factory=uuid4, description="唯一标识")
    name: str = Field(description="产品名称")
    company: str = Field(default="", description="所属公司")
    website: str = Field(default="", description="官网地址")
    category: str = Field(default="", description="产品分类")
    description: str = Field(default="", description="产品简介")
    target_market: str = Field(default="", description="目标市场/用户群")
    core_features: list[Feature] = Field(default_factory=list, description="核心功能列表")
    pricing: Pricing | None = Field(default=None, description="定价信息")
    strengths: list[AnnotatedFinding] = Field(
        default_factory=list, description="优势（每条绑定证据）"
    )
    weaknesses: list[AnnotatedFinding] = Field(
        default_factory=list, description="劣势（每条绑定证据）"
    )
    data_sources: list[Evidence] = Field(
        default_factory=list, description="所有数据采集来源汇总"
    )
    collected_at: datetime = Field(default_factory=datetime.now, description="采集时间")


class FeatureMatrix(BaseModel):
    """功能对比矩阵 — 分析 Agent 输出（MVP 阶段建议单竞品使用，后续扩展多竞品）"""

    id: UUID = Field(default_factory=uuid4)
    competitors: list[str] = Field(description="参与对比的竞品名称列表")
    dimensions: list[str] = Field(description="对比维度（如：核心功能、定价、体验）")
    matrix: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description="二维矩阵: {维度: {竞品名: 评价}}",
    )
    summary: str = Field(default="", description="对比总结")
    evidence_list: list[Evidence] = Field(
        default_factory=list, description="支撑对比结论的证据列表"
    )
    generated_at: datetime = Field(default_factory=datetime.now)


class SWOTItem(BaseModel):
    """SWOT 分析项"""

    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    threats: list[str] = Field(default_factory=list)


class MarketInsight(BaseModel):
    """市场洞察 — 分析 Agent 输出"""

    id: UUID = Field(default_factory=uuid4)
    competitor_name: str = Field(description="分析对象")
    swot: SWOTItem = Field(default_factory=SWOTItem)
    market_position: str = Field(default="", description="市场定位描述")
    differentiation_points: list[AnnotatedFinding] = Field(
        default_factory=list, description="差异化优势（每条绑定证据）"
    )
    trends: list[AnnotatedFinding] = Field(
        default_factory=list, description="趋势洞察（每条绑定证据）"
    )
    evidence_list: list[Evidence] = Field(
        default_factory=list, description="支撑洞察的全部证据列表"
    )
    generated_at: datetime = Field(default_factory=datetime.now)


class StructuredReport(BaseModel):
    """结构化竞品报告 — 撰写 Agent 的主输出"""

    id: UUID = Field(default_factory=uuid4)
    title: str = Field(description="报告标题")
    executive_summary: str = Field(description="执行摘要")
    competitor_profiles: list[CompetitorProfile] = Field(
        default_factory=list, description="竞品画像列表"
    )
    feature_matrix: FeatureMatrix | None = Field(
        default=None, description="功能对比矩阵"
    )
    market_insights: list[MarketInsight] = Field(
        default_factory=list, description="市场洞察列表"
    )
    strategic_recommendations: list[str] = Field(
        default_factory=list, description="战略建议"
    )
    review_result: ReviewResult | None = Field(
        default=None, description="质检结果"
    )
    trace_id: str = Field(
        default_factory=lambda: str(uuid4()), description="全链路追踪 ID"
    )
    generated_at: datetime = Field(default_factory=datetime.now)


# ============================================================
# LangGraph 全局状态
# ============================================================

class AgentState(TypedDict):
    """LangGraph 全局状态 — 所有 Agent 节点共享

    使用 TypedDict 而非 Pydantic Model，因为 LangGraph 的 StateGraph
    原生支持 TypedDict + Annotated reducer 模式。
    """

    # --- 用户输入 ---
    target_product: str                          # 待分析的竞品名称
    analysis_dimensions: list[str]               # 分析维度列表

    # --- 中间产物 ---
    source_pool: list[dict]                      # 信源池（Collector 输出，序列化为 dict）
    competitor_profiles: list[dict]              # 竞品画像（Collector → Analyst → Writer）
    feature_matrix: dict | None               # 功能对比矩阵（Analyst 输出）
    market_insights: list[dict]                  # 市场洞察（Analyst 输出）

    # --- Writer 输出 ---
    report: str                                  # 最终报告 Markdown

    # --- Reviewer 控制流 ---
    review_result: dict | None                # 质检结论（dict 化的 ReviewResult）

    # --- 控制流状态 ---
    iteration_count: Annotated[int, operator.add]  # 质检-修正循环计数（自动累加）
    messages: Annotated[list, operator.add]        # 全局消息日志（自动追加）


# ============================================================
# 代码审查相关枚举 (Product Line 2: Code Review)
# ============================================================

class AgentType(str, Enum):
    """审查 Agent 类型枚举"""
    CLAUDE = "claude"                # Claude Code — 架构/安全/性能
    CODEX = "codex"                  # Codex CLI — 实现/边界/测试
    SECURITY_AUDITOR = "security_auditor"
    PERFORMANCE_REVIEWER = "performance_reviewer"


class IssueCategory(str, Enum):
    """审查问题分类"""
    ARCHITECTURE = "architecture"           # 架构设计
    SECURITY = "security"                   # 安全漏洞
    PERFORMANCE = "performance"             # 性能问题
    BUG = "bug"                             # 潜在 Bug
    STYLE = "style"                         # 代码风格
    TEST_COVERAGE = "test_coverage"         # 测试覆盖
    MAINTAINABILITY = "maintainability"     # 可维护性
    BEST_PRACTICE = "best_practice"         # 最佳实践


class Priority(str, Enum):
    """问题优先级"""
    P0_CRITICAL = "P0"   # 阻塞合并 — 必须立即修复
    P1_HIGH = "P1"       # 高优先级 — 合并前修复
    P2_MEDIUM = "P2"     # 中优先级 — 建议修复
    P3_LOW = "P3"        # 低优先级 — 可选修复


# ============================================================
# 代码审查数据模型 (Product Line 2)
# ============================================================

class FileChange(BaseModel):
    """单个文件变更"""

    path: str = Field(description="文件路径")
    change_type: str = Field(default="modified", description="变更类型: added/modified/deleted")
    additions: int = Field(default=0, ge=0, description="新增行数")
    deletions: int = Field(default=0, ge=0, description="删除行数")
    diff: str = Field(default="", description="unified diff patch 文本")
    language: str = Field(default="", description="编程语言")


class PullRequest(BaseModel):
    """PR 基本信息"""

    id: UUID = Field(default_factory=uuid4)
    title: str = Field(description="PR 标题")
    description: str = Field(default="", description="PR 描述")
    author: str = Field(default="", description="提交者")
    source_branch: str = Field(default="", description="源分支")
    target_branch: str = Field(default="main", description="目标分支")
    repo: str = Field(default="", description="仓库名")
    changed_files: list[FileChange] = Field(default_factory=list, description="变更文件列表")
    total_additions: int = Field(default=0, description="总新增行数")
    total_deletions: int = Field(default=0, description="总删除行数")
    labels: list[str] = Field(default_factory=list, description="PR 标签")
    created_at: datetime = Field(default_factory=datetime.now)

    @property
    def total_changes(self) -> int:
        """变更总行数"""
        return self.total_additions + self.total_deletions

    @property
    def change_size(self) -> str:
        """变更规模分类: small / medium / large"""
        ch = self.total_changes
        if ch < 50:
            return "small"
        elif ch < 200:
            return "medium"
        else:
            return "large"

    @property
    def dominant_file_types(self) -> list[str]:
        """主要变更文件类型（去重排序）"""
        types = list({f.language for f in self.changed_files if f.language})
        return types[:5]


class ReviewIssue(BaseModel):
    """审查发现的问题"""

    id: UUID = Field(default_factory=uuid4)
    category: IssueCategory = Field(description="问题分类")
    priority: Priority = Field(description="优先级 P0-P3")
    title: str = Field(description="问题标题（一句话摘要）")
    description: str = Field(default="", description="详细描述")
    file_path: str = Field(default="", description="问题所在文件路径")
    line_number: int | None = Field(default=None, description="问题所在行号")
    suggested_fix: str = Field(default="", description="建议修复方案")
    evidence: Evidence | None = Field(default=None, description="支撑该发现的数据源/规则引用")
    agent_source: AgentType = Field(description="发现此问题的 Agent")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="AI 置信度")

    @property
    def is_critical(self) -> bool:
        return self.priority == Priority.P0_CRITICAL

    @property
    def is_high(self) -> bool:
        return self.priority in (Priority.P0_CRITICAL, Priority.P1_HIGH)


class ReviewScore(BaseModel):
    """六维审查评分"""

    overall: float = Field(default=0.0, ge=0.0, le=10.0, description="综合评分")
    architecture: float = Field(default=0.0, ge=0.0, le=10.0, description="架构设计评分")
    security: float = Field(default=0.0, ge=0.0, le=10.0, description="安全性评分")
    performance: float = Field(default=0.0, ge=0.0, le=10.0, description="性能评分")
    test_coverage: float = Field(default=0.0, ge=0.0, le=10.0, description="测试覆盖评分")
    maintainability: float = Field(default=0.0, ge=0.0, le=10.0, description="可维护性评分")

    def compute_overall(self) -> float:
        """计算综合评分（加权平均）"""
        weights = {
            "architecture": 0.25, "security": 0.25, "performance": 0.15,
            "test_coverage": 0.15, "maintainability": 0.20,
        }
        self.overall = round(
            self.architecture * weights["architecture"]
            + self.security * weights["security"]
            + self.performance * weights["performance"]
            + self.test_coverage * weights["test_coverage"]
            + self.maintainability * weights["maintainability"],
            1,
        )
        return self.overall

    def passes_quality_gate(
        self,
        min_overall: float = 6.0,
        min_security: float = 7.0,
        min_performance: float = 6.0,
        min_test_coverage: float = 5.0,
    ) -> tuple[bool, list[str]]:
        """判断是否通过质量门禁，返回 (通过, 失败维度列表)"""
        failures = []
        if self.overall < min_overall:
            failures.append(f"overall ({self.overall} < {min_overall})")
        if self.security < min_security:
            failures.append(f"security ({self.security} < {min_security})")
        if self.performance < min_performance:
            failures.append(f"performance ({self.performance} < {min_performance})")
        if self.test_coverage < min_test_coverage:
            failures.append(f"test_coverage ({self.test_coverage} < {min_test_coverage})")
        return (len(failures) == 0, failures)

    def auto_approvable(
        self,
        threshold: float = 8.5,
        critical_count: int = 0,
        high_count: int = 0,
    ) -> bool:
        """判断是否可自动批准"""
        return self.overall >= threshold and critical_count == 0 and high_count <= 1


class ReviewReport(BaseModel):
    """完整代码审查报告"""

    id: UUID = Field(default_factory=uuid4)
    pr: PullRequest = Field(description="审查的 PR 信息")
    issues: list[ReviewIssue] = Field(default_factory=list, description="发现的问题列表")
    score: ReviewScore = Field(default_factory=ReviewScore, description="六维评分")
    selected_agents: list[AgentType] = Field(default_factory=list, description="参与审查的 Agent")
    quality_gate_passed: bool = Field(default=False, description="是否通过质量门禁")
    quality_gate_failures: list[str] = Field(default_factory=list, description="质量门禁失败项")
    dora_metrics: dict | None = Field(default=None, description="关联的 DORA 指标")
    agenthub_metrics: dict | None = Field(default=None, description="关联的 AgentHub 指标")
    trace_id: str = Field(default_factory=lambda: str(uuid4()), description="全链路追踪 ID")
    generated_at: datetime = Field(default_factory=datetime.now)

    def render_markdown(self) -> str:
        """渲染为 Markdown 审查报告"""
        lines = [
            f"# 🔍 Code Review Report",
            f"",
            f"## 1. Executive Summary",
            f"",
            f"- **PR**: {self.pr.title}",
            f"- **Author**: {self.pr.author}",
            f"- **Branch**: {self.pr.source_branch} → {self.pr.target_branch}",
            f"- **Changes**: +{self.pr.total_additions}/-{self.pr.total_deletions} lines "
            f"({len(self.pr.changed_files)} files)",
            f"- **Reviewers**: {', '.join(a.value for a in self.selected_agents)}",
            f"",
            f"### Overall Score: {self.score.overall}/10",
            f"",
            f"| Dimension | Score |",
            f"|-----------|-------|",
            f"| Architecture | {self.score.architecture}/10 |",
            f"| Security | {self.score.security}/10 |",
            f"| Performance | {self.score.performance}/10 |",
            f"| Test Coverage | {self.score.test_coverage}/10 |",
            f"| Maintainability | {self.score.maintainability}/10 |",
            f"",
            f"### Quality Gate: {'✅ PASSED' if self.quality_gate_passed else '❌ FAILED'}",
        ]
        if not self.quality_gate_passed:
            lines.append("")
            for f in self.quality_gate_failures:
                lines.append(f"- ❌ {f}")
            lines.append("")

        # Issues by category
        lines.append("")
        lines.append("## 2. Issues Found")
        lines.append("")
        by_cat: dict[str, list[ReviewIssue]] = {}
        for issue in self.issues:
            cat = issue.category.value
            by_cat.setdefault(cat, []).append(issue)

        for cat, items in sorted(by_cat.items()):
            lines.append(f"### {cat.replace('_', ' ').title()} ({len(items)} issues)")
            lines.append("")
            for item in sorted(items, key=lambda x: x.priority.value):
                icon = "🔴" if item.priority == Priority.P0_CRITICAL else \
                       "🟠" if item.priority == Priority.P1_HIGH else \
                       "🟡" if item.priority == Priority.P2_MEDIUM else "🟢"
                lines.append(f"- {icon} **[{item.priority.value}] {item.title}**")
                if item.file_path:
                    loc = f"`{item.file_path}`"
                    if item.line_number:
                        loc += f":{item.line_number}"
                    lines.append(f"  - Location: {loc}")
                lines.append(f"  - Source: {item.agent_source.value}")
                if item.suggested_fix:
                    lines.append(f"  - Fix: {item.suggested_fix}")
                lines.append("")

        # Evidence trace
        lines.append("## 8. Evidence Trace")
        lines.append("")
        for i, issue in enumerate(self.issues):
            if issue.evidence:
                e = issue.evidence
                lines.append(f"{i+1}. [{issue.id}] {issue.title} — {e.source_title} ({e.source_url})")
            else:
                lines.append(f"{i+1}. [{issue.id}] {issue.title} — AI-generated, no external source")

        return "\n".join(lines)


class DORAMetrics(BaseModel):
    """DORA 核心四指标"""

    deployment_frequency: float = Field(default=0.0, ge=0.0, description="部署频率（次/周）")
    lead_time_hours: float = Field(default=0.0, ge=0.0, description="变更交付周期（小时）")
    change_failure_rate: float = Field(default=0.0, ge=0.0, le=100.0, description="变更失败率（%）")
    mttr_hours: float = Field(default=0.0, ge=0.0, description="平均恢复时间（小时）")

    def performance_level(self) -> str:
        """根据 DORA 基准判定性能等级"""
        scores = 0
        if self.deployment_frequency >= 5:
            scores += 1
        if self.lead_time_hours <= 12:
            scores += 1
        if self.change_failure_rate <= 5:
            scores += 1
        if self.mttr_hours <= 3.6:
            scores += 1
        if scores == 4:
            return "elite"
        elif scores >= 2:
            return "high"
        elif scores >= 1:
            return "medium"
        return "low"

    def to_comparison(self, targets: dict) -> str:
        """生成 DORA 指标对比表（Markdown）"""
        lines = [
            "| Metric | Current | Target | Status |",
            "|--------|---------|--------|--------|",
            f"| Deployment Frequency | {self.deployment_frequency}/wk | {targets.get('deployment_frequency', 'N/A')}/wk | "
            f"{'✅' if self.deployment_frequency >= targets.get('deployment_frequency', 999) else '⬆️'} |",
            f"| Lead Time | {self.lead_time_hours}h | {targets.get('lead_time_hours', 'N/A')}h | "
            f"{'✅' if self.lead_time_hours <= targets.get('lead_time_hours', -1) else '⬇️'} |",
            f"| Change Failure Rate | {self.change_failure_rate}% | {targets.get('change_failure_rate', 'N/A')}% | "
            f"{'✅' if self.change_failure_rate <= targets.get('change_failure_rate', -1) else '⬇️'} |",
            f"| MTTR | {self.mttr_hours}h | {targets.get('mttr_hours', 'N/A')}h | "
            f"{'✅' if self.mttr_hours <= targets.get('mttr_hours', 999) else '⬇️'} |",
            "",
            f"**Performance Level: {self.performance_level().upper()}**",
        ]
        return "\n".join(lines)


class AgentHubMetrics(BaseModel):
    """AgentHub 专属七指标"""

    ai_review_coverage: float = Field(default=0.0, ge=0.0, le=1.0, description="AI 审查覆盖率")
    ai_issue_detection_rate: float = Field(default=0.0, ge=0.0, le=1.0, description="AI 有效发现率")
    ai_fix_adoption_rate: float = Field(default=0.0, ge=0.0, le=1.0, description="修复采纳率")
    human_review_time_saved_pct: float = Field(default=0.0, ge=0.0, le=1.0, description="人工审查时间节省比例")
    multi_agent_efficiency_gain: float = Field(default=0.0, ge=0.0, description="多 Agent 效率增益")
    agent_utilization_balance: float = Field(default=0.0, ge=0.0, description="Agent 负载均衡差异")
    cost_per_review_usd: float = Field(default=0.0, ge=0.0, description="每次审查成本（美元）")

    def to_summary(self, targets: dict) -> str:
        """生成指标摘要表（Markdown）"""
        lines = [
            "| Metric | Current | Target | Status |",
            "|--------|---------|--------|--------|",
        ]
        metrics = [
            ("AI Review Coverage", self.ai_review_coverage, targets.get("ai_review_coverage"), ">="),
            ("AI Issue Detection Rate", self.ai_issue_detection_rate, targets.get("ai_issue_detection_rate"), ">="),
            ("AI Fix Adoption Rate", self.ai_fix_adoption_rate, targets.get("ai_fix_adoption_rate"), ">="),
            ("Human Review Time Saved", self.human_review_time_saved_pct, targets.get("human_review_time_saved"), ">="),
            ("Multi-Agent Efficiency", self.multi_agent_efficiency_gain, targets.get("multi_agent_efficiency"), ">="),
            ("Agent Utilization Balance", self.agent_utilization_balance, targets.get("agent_utilization_balance"), "<="),
            ("Cost Per Review", self.cost_per_review_usd, targets.get("cost_per_review_usd"), "<="),
        ]
        for name, current, target, op in metrics:
            if target is not None:
                if op == ">=":
                    ok = current >= target
                elif op == "<=":
                    ok = current <= target
                else:
                    ok = True
                status = "✅" if ok else "⬆️"
            else:
                status = "—"
            lines.append(
                f"| {name} | {current:.1%} | {target if target else 'N/A'} | {status} |"
            )
        return "\n".join(lines)
