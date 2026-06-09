"""
竞品知识 Schema 定义

所有 Agent 共享的统一数据结构，基于 Pydantic V2。
设计原则：
  - 核心字段采用 AnnotatedFinding 实现字段级溯源
  - ReviewResult 含 RejectReason 枚举，支撑 LangGraph 条件路由
  - 所有 URL 字段统一为 str，避免 Pydantic V2 Url 对象序列化异常
  - AgentState TypedDict 作为 LangGraph 全局状态
"""

from datetime import datetime
from enum import Enum
from typing import Annotated, Optional
from uuid import UUID, uuid4

import operator
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
    evidence: Optional[Evidence] = Field(default=None, description="功能信息来源")


class Pricing(BaseModel):
    """定价信息"""

    model: str = Field(description="定价模式：免费/订阅/买断/按量")
    starting_price: str = Field(default="", description="起售价")
    details: str = Field(default="", description="定价详情")
    source: Optional[Evidence] = Field(default=None, description="定价信息来源")


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
    pricing: Optional[Pricing] = Field(default=None, description="定价信息")
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
    feature_matrix: Optional[FeatureMatrix] = Field(
        default=None, description="功能对比矩阵"
    )
    market_insights: list[MarketInsight] = Field(
        default_factory=list, description="市场洞察列表"
    )
    strategic_recommendations: list[str] = Field(
        default_factory=list, description="战略建议"
    )
    review_result: Optional[ReviewResult] = Field(
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
    feature_matrix: Optional[dict]               # 功能对比矩阵（Analyst 输出）
    market_insights: list[dict]                  # 市场洞察（Analyst 输出）

    # --- Writer 输出 ---
    report: str                                  # 最终报告 Markdown

    # --- Reviewer 控制流 ---
    review_result: Optional[dict]                # 质检结论（dict 化的 ReviewResult）

    # --- 控制流状态 ---
    iteration_count: Annotated[int, operator.add]  # 质检-修正循环计数（自动累加）
    messages: Annotated[list, operator.add]        # 全局消息日志（自动追加）
