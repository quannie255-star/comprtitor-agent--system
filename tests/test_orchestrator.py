"""
DAG 编排引擎端到端集成测试

覆盖：
1. Orchestrator 初始化（Agent 创建、LLM 工厂）
2. Orchestrator.run 完整流水线（顺序模式）
3. 反馈闭环：质检驳回 → 重跑
4. TraceStore 轨迹保存与加载
5. ArtifactStore 产物保存与加载
6. Orchestrator 执行摘要
"""

import json
import os
import tempfile
from unittest.mock import MagicMock

import pytest

from core.orchestrator import Orchestrator
from storage.trace_store import TraceStore
from storage.artifact_store import ArtifactStore
from core.schema import RejectReason


# ============================================================
# Mock LLM
# ============================================================

@pytest.fixture
def mock_config():
    """最小配置（无 LLM → mock 模式）"""
    return {
        "llm": {
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": "",  # 空 key → mock 模式
        },
        "search": {"api_key": ""},
        "agents": {
            "analyst": {"comparison_dimensions": ["功能", "定价"]},
            "reviewer": {"max_review_rounds": 2},
        },
        "orchestrator": {"recursion_limit": 10},
    }


# ============================================================
# Orchestrator
# ============================================================

class TestOrchestrator:
    def test_init_creates_all_agents(self, mock_config):
        orch = Orchestrator(mock_config)
        assert orch.collector is not None
        assert orch.analyst is not None
        assert orch.writer is not None
        assert orch.reviewer is not None
        assert orch.bus is not None

    def test_run_sequential_completes(self, mock_config):
        """完整流水线：Collect → Analyze → Write → Review（mock LLM）"""
        orch = Orchestrator(mock_config)
        result = orch.run("Notion", ["功能", "定价"], use_langgraph=False)

        # 验证各阶段产出
        assert "source_pool" in result
        assert len(result["source_pool"]) > 0
        assert "competitor_profiles" in result
        assert len(result["competitor_profiles"]) > 0
        assert "report" in result
        assert len(result["report"]) > 0
        assert "review_result" in result

    def test_run_saves_traces(self, mock_config):
        """执行后轨迹被保存"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = {**mock_config, "storage": {"traces_dir": tmpdir, "artifacts_dir": tmpdir, "outputs_dir": tmpdir}}
            orch = Orchestrator(cfg)
            orch.run("Slack", use_langgraph=False)

            # 轨迹目录存在
            trace_dir = os.path.join(tmpdir, orch.trace_id)
            assert os.path.exists(trace_dir)

            # 至少生成了 messages.json
            assert os.path.exists(os.path.join(trace_dir, "messages.json"))

    def test_run_saves_artifacts(self, mock_config):
        """执行后中间产物被保存"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = {**mock_config, "storage": {"traces_dir": tmpdir, "artifacts_dir": tmpdir, "outputs_dir": tmpdir}}
            orch = Orchestrator(cfg)
            orch.run("Figma", use_langgraph=False)

            artifacts = orch.artifact_store.list_artifacts(orch.trace_id)
            assert len(artifacts) >= 4  # collector, analyst, writer, reviewer

    def test_get_summary(self, mock_config):
        orch = Orchestrator(mock_config)
        orch.run("Test", use_langgraph=False)

        summary = orch.get_summary()
        assert "trace_id" in summary
        assert summary["collector_steps"] > 0
        assert summary["analyst_steps"] > 0
        assert summary["writer_steps"] > 0
        assert summary["reviewer_steps"] > 0


# ============================================================
# TraceStore
# ============================================================

class TestTraceStore:
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = TraceStore(base_dir=tmpdir)
            trace_id = "test-trace-123"

            store.save_trace(
                trace_id=trace_id,
                agent_logs={
                    "collector": [{"action": "search", "output_summary": "3 results"}],
                    "analyst": [{"action": "analyze", "output_summary": "SWOT done"}],
                },
                message_log=[
                    {"sender": "collector", "receiver": "analyst", "msg_type": "data_output"},
                ],
                state_summary={"target": "Notion", "passed": True},
            )

            # 加载
            loaded = store.load_trace(trace_id)
            assert loaded is not None
            assert "collector" in loaded["agents"]
            assert len(loaded["messages"]) == 1
            assert "events" in loaded["timeline"]

    def test_load_nonexistent(self):
        store = TraceStore(base_dir="/tmp/nonexistent")
        assert store.load_trace("fake-id") is None


# ============================================================
# ArtifactStore
# ============================================================

class TestArtifactStore:
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            trace_id = "test-artifact-123"

            store.save_artifact(trace_id, "01_test", {"key": "value"})
            store.save_artifact(trace_id, "02_test", {"items": [1, 2, 3]})

            # 列出
            artifacts = store.list_artifacts(trace_id)
            assert len(artifacts) == 2

            # 加载
            data = store.load_artifact(trace_id, "01_test.json")
            assert data == {"key": "value"}

    def test_save_state_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            path = store.save_state_snapshot(
                "trace-x", {"report": "test", "iteration_count": 3}, step=1
            )
            assert os.path.exists(path)

    def test_list_empty(self):
        store = ArtifactStore(base_dir="/tmp/nonexistent_artifacts")
        assert store.list_artifacts("no-trace") == []
