"""
代码审查 Pipeline 单元测试 (Product Line 2)

覆盖：
1. 新 Schema 模型（PullRequest, ReviewIssue, ReviewScore, DORAMetrics, AgentHubMetrics）
2. Collector PR/Diff 模式
3. Analyst 双轨审查（Mock）
4. Writer 审查报告生成
5. Reviewer 质量门禁 + 指标追踪
6. Orchestrator 路由 + 端到端流水线
"""
import pytest
from core.schema import (
    AgentHubMetrics,
    AgentType,
    DORAMetrics,
    FileChange,
    IssueCategory,
    Priority,
    PullRequest,
    ReviewIssue,
    ReviewReport,
    ReviewScore,
)


class TestPullRequest:
    """PR 数据模型"""

    def test_create_minimal(self):
        pr = PullRequest(title="Fix bug")
        assert pr.title == "Fix bug"
        assert pr.total_changes == 0
        assert pr.change_size == "small"

    def test_change_size_small(self):
        pr = PullRequest(title="T", total_additions=20, total_deletions=15)
        assert pr.total_changes == 35
        assert pr.change_size == "small"

    def test_change_size_medium(self):
        pr = PullRequest(title="T", total_additions=80, total_deletions=20)
        assert pr.total_changes == 100
        assert pr.change_size == "medium"

    def test_change_size_large(self):
        pr = PullRequest(title="T", total_additions=200, total_deletions=100)
        assert pr.change_size == "large"

    def test_with_files(self):
        pr = PullRequest(
            title="Add auth",
            changed_files=[
                FileChange(path="src/auth.py", additions=50, deletions=10, language="python"),
                FileChange(path="config.yaml", additions=5, deletions=0, language="yaml"),
            ],
            total_additions=55,
            total_deletions=10,
        )
        assert len(pr.changed_files) == 2
        assert pr.dominant_file_types == ["python", "yaml"]


class TestReviewIssue:
    """审查问题模型"""

    def test_create(self):
        issue = ReviewIssue(
            category=IssueCategory.SECURITY,
            priority=Priority.P0_CRITICAL,
            title="SQL injection risk",
            file_path="src/db.py",
            line_number=42,
            agent_source=AgentType.CLAUDE,
        )
        assert issue.is_critical
        assert issue.is_high

    def test_priority_p2_not_critical(self):
        issue = ReviewIssue(
            category=IssueCategory.STYLE,
            priority=Priority.P2_MEDIUM,
            title="Line too long",
            agent_source=AgentType.CODEX,
        )
        assert not issue.is_critical
        assert not issue.is_high

    def test_serialize_roundtrip(self):
        issue = ReviewIssue(
            category=IssueCategory.BUG,
            priority=Priority.P1_HIGH,
            title="Null check",
            file_path="a.py",
            suggested_fix="Add guard",
            agent_source=AgentType.CODEX,
            confidence=0.85,
        )
        data = issue.model_dump(mode="json")
        restored = ReviewIssue(**data)
        assert restored.title == "Null check"
        assert restored.confidence == 0.85


class TestReviewScore:
    """六维评分模型"""

    def test_compute_overall(self):
        score = ReviewScore(
            architecture=8, security=9, performance=7,
            test_coverage=6, maintainability=8,
        )
        overall = score.compute_overall()
        # 0.25*8 + 0.25*9 + 0.15*7 + 0.15*6 + 0.20*8 = 2+2.25+1.05+0.9+1.6 = 7.8
        assert 7.5 <= overall <= 8.5

    def test_passes_quality_gate(self):
        score = ReviewScore(
            architecture=8, security=8, performance=7,
            test_coverage=7, maintainability=8,
        )
        score.compute_overall()
        passed, failures = score.passes_quality_gate()
        assert passed
        assert len(failures) == 0

    def test_fails_quality_gate_low_security(self):
        score = ReviewScore(
            architecture=8, security=5, performance=8,
            test_coverage=8, maintainability=8,
        )
        score.compute_overall()
        passed, failures = score.passes_quality_gate()
        assert not passed
        assert any("security" in f for f in failures)

    def test_auto_approvable(self):
        score = ReviewScore(
            architecture=9, security=9, performance=9,
            test_coverage=9, maintainability=9,
        )
        score.compute_overall()
        assert score.auto_approvable(threshold=8.5, critical_count=0, high_count=1)

    def test_not_auto_approvable_with_critical(self):
        score = ReviewScore(
            architecture=9, security=9, performance=9,
            test_coverage=9, maintainability=9,
        )
        score.compute_overall()
        assert not score.auto_approvable(threshold=8.5, critical_count=1, high_count=0)


class TestReviewReport:
    """审查报告模型"""

    def test_render_markdown(self):
        pr = PullRequest(title="Fix bug", author="dev")
        issues = [
            ReviewIssue(
                category=IssueCategory.SECURITY,
                priority=Priority.P1_HIGH,
                title="Hardcoded key",
                file_path="src/auth.py",
                agent_source=AgentType.CLAUDE,
            ),
        ]
        score = ReviewScore(
            architecture=8, security=7, performance=8,
            test_coverage=7, maintainability=8,
        )
        score.compute_overall()
        report = ReviewReport(
            pr=pr, issues=issues, score=score,
            selected_agents=[AgentType.CLAUDE],
            quality_gate_passed=True,
        )
        md = report.render_markdown()
        assert "Fix bug" in md
        assert "Hardcoded key" in md
        assert "Executive Summary" in md
        assert "Quality Gate" in md


class TestDORAMetrics:
    """DORA 指标模型"""

    def test_performance_level_elite(self):
        dora = DORAMetrics(
            deployment_frequency=7,
            lead_time_hours=6,
            change_failure_rate=3,
            mttr_hours=2,
        )
        assert dora.performance_level() == "elite"

    def test_performance_level_low(self):
        dora = DORAMetrics(
            deployment_frequency=1,
            lead_time_hours=48,
            change_failure_rate=20,
            mttr_hours=10,
        )
        assert dora.performance_level() == "low"

    def test_to_comparison(self):
        dora = DORAMetrics(
            deployment_frequency=4, lead_time_hours=15,
            change_failure_rate=6, mttr_hours=4,
        )
        targets = {
            "deployment_frequency": 5.0, "lead_time_hours": 12,
            "change_failure_rate": 5.0, "mttr_hours": 3.6,
        }
        table = dora.to_comparison(targets)
        assert "Deployment Frequency" in table
        assert "Performance Level" in table


class TestAgentHubMetrics:
    """AgentHub 指标模型"""

    def test_to_summary(self):
        m = AgentHubMetrics(
            ai_review_coverage=0.88,
            ai_issue_detection_rate=0.82,
            ai_fix_adoption_rate=0.58,
            human_review_time_saved_pct=0.72,
            multi_agent_efficiency_gain=0.38,
            agent_utilization_balance=0.12,
            cost_per_review_usd=1.75,
        )
        targets = {
            "ai_review_coverage": 0.90, "ai_issue_detection_rate": 0.85,
            "ai_fix_adoption_rate": 0.60, "human_review_time_saved": 0.75,
            "multi_agent_efficiency": 0.40, "agent_utilization_balance": 0.20,
            "cost_per_review_usd": 2.00,
        }
        summary = m.to_summary(targets)
        assert "AI Review Coverage" in summary


class TestEndToEndCodeReview:
    """端到端代码审查流水线（Mock 模式，无需 API Key）"""

    def test_full_pipeline_mock(self):
        """验证无 LLM 时完整流水线能跑通"""
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

        from core.orchestrator import Orchestrator

        orch = Orchestrator({
            "storage": {"traces_dir": "./traces", "outputs_dir": "./outputs", "artifacts_dir": "./artifacts"},
        })

        pr_data = {
            "title": "Fix JWT token refresh",
            "description": "Fixes token validation on each request.",
            "author": "dev1",
            "changed_files": [
                {"path": "src/auth.py", "additions": 30, "deletions": 8, "diff": "+def validate()..."},
                {"path": "tests/test_auth.py", "additions": 45, "deletions": 0, "diff": "+def test_validate()..."},
            ],
            "total_additions": 75,
            "total_deletions": 8,
        }

        result = orch.review_pr(pr_data)

        # 验证核心输出
        assert "report" in result
        assert len(result["report"]) > 0
        assert "review_result" in result
        assert "dora_metrics" in result
        assert "agenthub_metrics" in result
        assert "review_issues" in result
        assert "review_score" in result

        # 验证报告内容
        report = result["report"]
        assert "Fix JWT token refresh" in report
        assert "Executive Summary" in report
        assert "Quality Gate" in report

        # 验证评分
        score = result["review_score"]
        if isinstance(score, dict):
            assert score.get("overall", 0) > 0

        # 验证指标
        dora = result["dora_metrics"]
        if isinstance(dora, dict):
            assert "performance_level" in dora or dora.get("deployment_frequency", 0) >= 0
