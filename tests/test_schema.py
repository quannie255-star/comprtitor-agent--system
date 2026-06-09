"""
竞品知识 Schema 单元测试

覆盖：
1. 基础模型（Evidence, AnnotatedFinding, Feature, Pricing）实例化
2. RejectReason 枚举与 ReviewResult 条件路由
3. CompetitorProfile 字段级溯源（AnnotatedFinding）
4. FeatureMatrix / MarketInsight / StructuredReport 创建与 JSON 往返
5. AgentState TypedDict 结构验证
"""

import json
from datetime import datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from core.schema import (
    AgentState,
    AnnotatedFinding,
    CompetitorProfile,
    Evidence,
    Feature,
    FeatureMatrix,
    MarketInsight,
    Pricing,
    RejectReason,
    ReviewResult,
    StructuredReport,
    SWOTItem,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def sample_evidence():
    return Evidence(
        source_id="src_001",
        source_url="https://www.notion.so/pricing",
        source_title="Notion 官方定价页",
        excerpt="Notion Plus 计划定价为 $10/月",
        confidence=0.95,
    )


@pytest.fixture
def sample_competitor(sample_evidence):
    strength = AnnotatedFinding(
        content="界面直观易用，学习曲线低",
        evidence=sample_evidence,
    )
    weakness = AnnotatedFinding(
        content="离线支持较弱",
        evidence=sample_evidence,
    )
    feature = Feature(
        name="实时协作",
        description="多人同时编辑文档",
        supported=True,
        evidence=sample_evidence,
    )
    pricing = Pricing(
        model="订阅制",
        starting_price="$10/月",
        source=sample_evidence,
    )
    return CompetitorProfile(
        name="Notion",
        company="Notion Labs Inc.",
        website="https://www.notion.so",
        category="协作知识库",
        description="一体化工作空间",
        core_features=[feature],
        pricing=pricing,
        strengths=[strength],
        weaknesses=[weakness],
        data_sources=[sample_evidence],
    )


# ============================================================
# Evidence
# ============================================================

class TestEvidence:
    def test_create_minimal(self):
        e = Evidence(source_id="s1", source_url="https://x.com", source_title="X", excerpt="...")
        assert e.confidence == 1.0

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            Evidence(source_id="s1", source_url="https://x.com", source_title="X", excerpt="...", confidence=1.5)

    def test_url_is_plain_str(self, sample_evidence):
        d = sample_evidence.model_dump(mode="json")
        assert isinstance(d["source_url"], str)
        assert d["source_url"] == "https://www.notion.so/pricing"


# ============================================================
# AnnotatedFinding
# ============================================================

class TestAnnotatedFinding:
    def test_create(self, sample_evidence):
        af = AnnotatedFinding(content="产品体验优秀", evidence=sample_evidence)
        assert af.content == "产品体验优秀"
        assert af.evidence.source_id == "src_001"

    def test_serialize_roundtrip(self, sample_evidence):
        af = AnnotatedFinding(content="测试", evidence=sample_evidence)
        reloaded = AnnotatedFinding.model_validate_json(af.model_dump_json())
        assert reloaded.content == af.content


# ============================================================
# RejectReason + ReviewResult
# ============================================================

class TestRejectReason:
    def test_enum_values(self):
        assert RejectReason.INSUFFICIENT_SOURCE == "insufficient_source"
        assert RejectReason.SCHEMA_MISMATCH == "schema_mismatch"
        assert RejectReason.QUALITY_ISSUE == "quality_issue"
        assert RejectReason.PASSED == "passed"

    def test_json_serializable(self):
        assert json.dumps(RejectReason.INSUFFICIENT_SOURCE) == '"insufficient_source"'


class TestReviewResult:
    def test_passed(self):
        rr = ReviewResult(passed=True, score=0.9)
        assert rr.reject_reason == RejectReason.PASSED

    def test_rejected_with_routing(self):
        rr = ReviewResult(
            passed=False,
            reject_reason=RejectReason.INSUFFICIENT_SOURCE,
            score=0.4,
            issues=["缺少官方来源"],
            missing_fields=["pricing.source"],
        )
        assert rr.reject_reason == RejectReason.INSUFFICIENT_SOURCE
        assert "pricing.source" in rr.missing_fields

    def test_routing_map_covers_all_paths(self):
        routing = {
            RejectReason.INSUFFICIENT_SOURCE: "collector",
            RejectReason.SCHEMA_MISMATCH: "analyst",
            RejectReason.QUALITY_ISSUE: "writer",
            RejectReason.PASSED: "done",
        }
        assert len(routing) == 4

    def test_serialize_roundtrip(self):
        rr = ReviewResult(passed=False, reject_reason=RejectReason.QUALITY_ISSUE, score=0.5)
        reloaded = ReviewResult.model_validate_json(rr.model_dump_json())
        assert reloaded.reject_reason == RejectReason.QUALITY_ISSUE


# ============================================================
# CompetitorProfile
# ============================================================

class TestCompetitorProfile:
    def test_create_minimal(self):
        c = CompetitorProfile(name="Slack")
        assert isinstance(c.id, UUID)
        assert c.strengths == []

    def test_field_level_traceability(self, sample_competitor):
        for s in sample_competitor.strengths:
            assert isinstance(s, AnnotatedFinding)
            assert s.evidence.source_url != ""
        for w in sample_competitor.weaknesses:
            assert isinstance(w, AnnotatedFinding)

    def test_serialize_roundtrip(self, sample_competitor):
        reloaded = CompetitorProfile.model_validate_json(sample_competitor.model_dump_json())
        assert reloaded.name == sample_competitor.name


# ============================================================
# FeatureMatrix
# ============================================================

class TestFeatureMatrix:
    def test_create_and_roundtrip(self):
        fm = FeatureMatrix(
            competitors=["A", "B"],
            dimensions=["价格"],
            matrix={"价格": {"A": "低", "B": "高"}},
            summary="A 更具优势",
        )
        reloaded = FeatureMatrix.model_validate_json(fm.model_dump_json())
        assert reloaded.competitors == fm.competitors


# ============================================================
# MarketInsight
# ============================================================

class TestMarketInsight:
    def test_create_and_roundtrip(self, sample_evidence):
        diff = AnnotatedFinding(content="差异化点", evidence=sample_evidence)
        mi = MarketInsight(competitor_name="Notion", swot=SWOTItem(), differentiation_points=[diff])
        reloaded = MarketInsight.model_validate_json(mi.model_dump_json())
        assert len(reloaded.differentiation_points) == 1


# ============================================================
# StructuredReport
# ============================================================

class TestStructuredReport:
    def test_create_empty(self):
        r = StructuredReport(title="T", executive_summary="S")
        assert isinstance(r.trace_id, str)
        UUID(r.trace_id)

    def test_full_roundtrip(self, sample_competitor):
        r = StructuredReport(
            title="报告", executive_summary="摘要",
            competitor_profiles=[sample_competitor],
            strategic_recommendations=["建议1"],
        )
        reloaded = StructuredReport.model_validate_json(r.model_dump_json())
        assert reloaded.title == r.title
        assert reloaded.trace_id == r.trace_id

    def test_review_integration(self):
        review = ReviewResult(passed=False, reject_reason=RejectReason.QUALITY_ISSUE, score=0.6)
        r = StructuredReport(title="T", executive_summary="S", review_result=review)
        assert r.review_result.passed is False


# ============================================================
# AgentState
# ============================================================

class TestAgentState:
    def test_create_minimal(self):
        state: AgentState = {
            "target_product": "Notion",
            "analysis_dimensions": ["功能"],
            "source_pool": [],
            "competitor_profiles": [],
            "feature_matrix": None,
            "market_insights": [],
            "report": "",
            "review_result": None,
            "iteration_count": 0,
            "messages": [],
        }
        assert state["target_product"] == "Notion"


# ============================================================
# 溯源完整性
# ============================================================

class TestTraceability:
    def test_competitor_field_level_evidence(self, sample_competitor):
        if sample_competitor.strengths:
            assert hasattr(sample_competitor.strengths[0], "evidence")

    def test_feature_matrix_has_evidence(self):
        fm = FeatureMatrix(competitors=["X"], dimensions=["Y"])
        assert hasattr(fm, "evidence_list")

    def test_report_has_trace_id(self):
        r = StructuredReport(title="T", executive_summary="S")
        assert r.trace_id
        UUID(r.trace_id)
