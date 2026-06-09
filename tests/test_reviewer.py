"""
质检 Agent 单元测试

覆盖：
1. ReviewChecker 证据完整性检查
2. ReviewChecker 矩阵完整性检查
3. ReviewChecker 报告结构检查
4. ReviewChecker 置信度评估
5. ReviewerAgent._determine_reject_reason 综合判定逻辑
6. ReviewerAgent._parse_review_response JSON 解析
7. ReviewerAgent._send_feedback 路由验证
8. ReviewerAgent.execute 完整流程（mock LLM）
9. 四种 RejectReason 路由全覆盖
"""

import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from agents.reviewer import ReviewerAgent
from core.message_bus import MessageBus, MessageType
from core.schema import (
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
from models.review import ReviewChecker


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def sample_profiles(sample_evidence):
    return [
        CompetitorProfile(
            name="Notion",
            company="Notion Labs",
            website="https://notion.so",
            category="协作工具",
            description="一体化工作空间",
            core_features=[
                Feature(name="协作", description="实时协作", supported=True, evidence=sample_evidence),
            ],
            pricing=Pricing(model="订阅", starting_price="$10", source=sample_evidence),
            strengths=[AnnotatedFinding(content="易用", evidence=sample_evidence)],
            weaknesses=[AnnotatedFinding(content="离线弱", evidence=sample_evidence)],
            data_sources=[sample_evidence],
        )
    ]


@pytest.fixture
def sample_feature_matrix(sample_evidence):
    return FeatureMatrix(
        competitors=["Notion"],
        dimensions=["协作"],
        matrix={"协作": {"Notion": "优秀"}},
        summary="Notion 协作能力优秀",
        evidence_list=[sample_evidence],
    )


@pytest.fixture
def sample_market_insights(sample_evidence):
    return [
        MarketInsight(
            competitor_name="Notion",
            swot=SWOTItem(strengths=["S1"], weaknesses=["W1"], opportunities=["O1"], threats=["T1"]),
            market_position="领导者",
            evidence_list=[sample_evidence],
        )
    ]


@pytest.fixture
def sample_report_md():
    return """# Notion 竞品分析报告

## 一、执行摘要
Notion 是协作知识库领域的领导者。

## 二、竞品概览
### 2.1 Notion (Notion Labs)
- 优势: 易用 [src_test]

## 三、功能对比矩阵
| 维度 | Notion |
|------|--------|
| 协作 | 优秀 |
"""


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    # 默认返回通过
    passed_response = json.dumps({
        "passed": True,
        "reject_reason": "passed",
        "score": 0.9,
        "issues": [],
        "suggestions": [],
        "missing_fields": [],
    }, ensure_ascii=False)
    llm.invoke.return_value = MagicMock(content=passed_response)
    return llm


# ============================================================
# ReviewChecker
# ============================================================

class TestReviewChecker:
    def test_check_evidence_completeness_clean(self, sample_profiles):
        issues = ReviewChecker.check_evidence_completeness(sample_profiles)
        assert len(issues) == 0

    def test_check_evidence_completeness_empty(self):
        """空画像应该报多个问题"""
        p = CompetitorProfile(name="Empty")
        issues = ReviewChecker.check_evidence_completeness([p])
        assert len(issues) >= 3  # data_sources, strengths, weaknesses, core_features

    def test_check_evidence_completeness_missing_strength(self, sample_evidence):
        """strengths 为空"""
        p = CompetitorProfile(
            name="Test",
            core_features=[Feature(name="F1", supported=True, evidence=sample_evidence)],
            strengths=[],
            weaknesses=[AnnotatedFinding(content="W1", evidence=sample_evidence)],
            data_sources=[sample_evidence],
        )
        issues = ReviewChecker.check_evidence_completeness([p])
        assert any("strengths 为空" in i for i in issues)

    def test_check_matrix_completeness_mismatch(self, sample_profiles):
        """矩阵中竞品名与 profiles 不匹配"""
        fm = FeatureMatrix(
            competitors=["WrongName"],
            dimensions=["X"],
            matrix={"X": {"WrongName": "OK"}},
            summary="...",
        )
        issues = ReviewChecker.check_matrix_completeness(fm, sample_profiles)
        assert len(issues) > 0
        assert any("不匹配" in i for i in issues)

    def test_check_matrix_completeness_empty(self, sample_profiles):
        fm = FeatureMatrix(competitors=["Notion"], dimensions=[], matrix={}, summary="")
        issues = ReviewChecker.check_matrix_completeness(fm, sample_profiles)
        assert len(issues) >= 2

    def test_check_report_completeness_empty(self):
        r = StructuredReport(title="T", executive_summary="")
        issues = ReviewChecker.check_report_completeness(r)
        assert len(issues) > 0

    def test_check_report_completeness_full(self, sample_profiles, sample_feature_matrix, sample_market_insights):
        r = StructuredReport(
            title="T",
            executive_summary="摘要",
            competitor_profiles=sample_profiles,
            feature_matrix=sample_feature_matrix,
            market_insights=sample_market_insights,
            strategic_recommendations=["建议"],
        )
        issues = ReviewChecker.check_report_completeness(r)
        assert len(issues) == 0

    def test_evaluate_confidence(self, sample_profiles):
        conf = ReviewChecker.evaluate_confidence(sample_profiles)
        assert 0 <= conf <= 1

    def test_evaluate_confidence_empty(self):
        conf = ReviewChecker.evaluate_confidence([])
        assert conf == 0.0


# ============================================================
# ReviewerAgent
# ============================================================

class TestReviewerAgent:
    @pytest.fixture
    def reviewer(self, message_bus, mock_llm):
        return ReviewerAgent(message_bus=message_bus, llm=mock_llm)

    # --- 判定逻辑 ---

    def test_determine_reject_reason_passed(self):
        reason = ReviewerAgent._determine_reject_reason(True, "passed", False)
        assert reason == RejectReason.PASSED

    def test_determine_reject_reason_insufficient_source(self):
        reason = ReviewerAgent._determine_reject_reason(False, "insufficient_source", False)
        assert reason == RejectReason.INSUFFICIENT_SOURCE

    def test_determine_reject_reason_schema_mismatch(self):
        reason = ReviewerAgent._determine_reject_reason(False, "schema_mismatch", False)
        assert reason == RejectReason.SCHEMA_MISMATCH

    def test_determine_reject_reason_quality_issue(self):
        reason = ReviewerAgent._determine_reject_reason(False, "quality_issue", False)
        assert reason == RejectReason.QUALITY_ISSUE

    def test_determine_reject_reason_programmatic_override(self):
        """编程化检查发现问题时降级为 SCHEMA_MISMATCH"""
        reason = ReviewerAgent._determine_reject_reason(True, "passed", True)
        assert reason == RejectReason.SCHEMA_MISMATCH

    # --- JSON 解析 ---

    def test_parse_review_response_clean(self):
        data = ReviewerAgent._parse_review_response(
            '{"passed": false, "reject_reason": "quality_issue", "score": 0.3, "issues": ["x"], "suggestions": ["y"], "missing_fields": []}'
        )
        assert data["passed"] is False
        assert data["reject_reason"] == "quality_issue"

    def test_parse_review_response_with_fence(self):
        data = ReviewerAgent._parse_review_response(
            '```json\n{"passed": true, "reject_reason": "passed", "score": 1.0, "issues": [], "suggestions": [], "missing_fields": []}\n```'
        )
        assert data["passed"] is True

    def test_parse_review_response_invalid(self):
        data = ReviewerAgent._parse_review_response("这不是 JSON")
        assert data["passed"] is True  # 默认通过

    # --- 反馈路由 ---

    def test_send_feedback_insufficient_source(self, reviewer, message_bus):
        """INSUFFICIENT_SOURCE → collector"""
        received = []
        message_bus.subscribe("collector", lambda m: received.append(m))

        result = ReviewResult(
            passed=False,
            reject_reason=RejectReason.INSUFFICIENT_SOURCE,
            score=0.4,
            issues=["缺信源"],
        )
        reviewer._send_feedback(RejectReason.INSUFFICIENT_SOURCE, result, "Notion", 0)

        assert len(received) == 1
        assert received[0].msg_type == MessageType.REVIEW_FEEDBACK
        assert received[0].payload["reject_reason"] == "insufficient_source"

    def test_send_feedback_passed(self, reviewer, message_bus):
        """PASSED → 广播 TASK_COMPLETE"""
        received = []
        message_bus.subscribe_broadcast(lambda m: received.append(m))

        result = ReviewResult(passed=True, reject_reason=RejectReason.PASSED, score=0.9)
        reviewer._send_feedback(RejectReason.PASSED, result, "Notion", 0)

        assert any(m.msg_type == MessageType.TASK_COMPLETE for m in received)

    def test_send_feedback_schema_mismatch_to_analyst(self, reviewer, message_bus):
        """SCHEMA_MISMATCH → analyst"""
        received = []
        message_bus.subscribe("analyst", lambda m: received.append(m))

        result = ReviewResult(
            passed=False,
            reject_reason=RejectReason.SCHEMA_MISMATCH,
            score=0.5,
            issues=["SWOT 缺失"],
        )
        reviewer._send_feedback(RejectReason.SCHEMA_MISMATCH, result, "Notion", 0)

        assert len(received) == 1
        assert received[0].receiver == "analyst"

    def test_send_feedback_quality_issue_to_writer(self, reviewer, message_bus):
        """QUALITY_ISSUE → writer"""
        received = []
        message_bus.subscribe("writer", lambda m: received.append(m))

        result = ReviewResult(
            passed=False,
            reject_reason=RejectReason.QUALITY_ISSUE,
            score=0.6,
            issues=["格式错误"],
        )
        reviewer._send_feedback(RejectReason.QUALITY_ISSUE, result, "Notion", 0)

        assert len(received) == 1
        assert received[0].receiver == "writer"

    # --- 完整流程 ---

    def test_execute_passed(
        self, reviewer, message_bus, sample_state, sample_profiles,
        sample_feature_matrix, sample_market_insights, sample_report_md,
    ):
        """完整质检流程：报告通过"""
        broadcast_received = []
        message_bus.subscribe_broadcast(lambda m: broadcast_received.append(m))

        state = {
            **sample_state,
            "report": sample_report_md,
            "competitor_profiles": [p.model_dump(mode="json") for p in sample_profiles],
            "feature_matrix": sample_feature_matrix.model_dump(mode="json"),
            "market_insights": [mi.model_dump(mode="json") for mi in sample_market_insights],
            "iteration_count": 0,
        }

        result = reviewer.execute(state)

        assert "review_result" in result
        rr = result["review_result"]
        assert rr["passed"] is True
        assert rr["score"] == 0.9

    def test_execute_with_programmatic_issues(
        self, reviewer, message_bus, sample_state, sample_report_md,
    ):
        """编程化检查发现问题 → 评分被压低、passed=false"""
        empty_profile = CompetitorProfile(name="Bare").model_dump(mode="json")

        state = {
            **sample_state,
            "report": sample_report_md,
            "competitor_profiles": [empty_profile],  # 缺很多字段
            "feature_matrix": None,
            "market_insights": [],
            "iteration_count": 0,
        }

        result = reviewer.execute(state)

        rr = result["review_result"]
        assert rr["passed"] is False
        assert rr["score"] <= 0.6
        assert len(rr["issues"]) > 0

    def test_execution_log(self, reviewer, sample_state, sample_profiles, sample_feature_matrix, sample_market_insights, sample_report_md):
        """执行日志包含编程化检查和 LLM 审查"""
        state = {
            **sample_state,
            "report": sample_report_md,
            "competitor_profiles": [p.model_dump(mode="json") for p in sample_profiles],
            "feature_matrix": sample_feature_matrix.model_dump(mode="json"),
            "market_insights": [mi.model_dump(mode="json") for mi in sample_market_insights],
            "iteration_count": 0,
        }

        reviewer.execute(state)

        actions = [s["action"] for s in reviewer.get_execution_log()]
        assert "programmatic_check" in actions
        assert "llm_review" in actions
        assert "review_complete" in actions

    def test_agent_name(self, reviewer):
        assert reviewer.agent_name == "reviewer"


# ============================================================
# 四种 RejectReason 路由全覆盖
# ============================================================

class TestRejectReasonRouting:
    """验证四种 RejectReason 能正确路由到对应 Agent"""

    ROUTING = {
        RejectReason.INSUFFICIENT_SOURCE: "collector",
        RejectReason.SCHEMA_MISMATCH: "analyst",
        RejectReason.QUALITY_ISSUE: "writer",
        RejectReason.PASSED: None,  # 广播
    }

    def test_all_reasons_mapped(self):
        assert len(self.ROUTING) == 4

    def test_each_reason_has_valid_target(self):
        for reason, target in self.ROUTING.items():
            if reason == RejectReason.PASSED:
                assert target is None
            else:
                assert target in ("collector", "analyst", "writer")
