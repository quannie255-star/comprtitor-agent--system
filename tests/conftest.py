"""
Pytest 共享 Fixtures

为所有测试模块提供：
  - MessageBus 实例
  - 示例 Evidence
  - 示例 Agent State
"""

import pytest

from core.message_bus import MessageBus
from core.schema import Evidence


@pytest.fixture
def message_bus():
    """创建带 trace_id 的 MessageBus"""
    return MessageBus(trace_id="test-trace-001")


@pytest.fixture
def sample_evidence():
    """示例证据"""
    return Evidence(
        source_id="src_test",
        source_url="https://example.com",
        source_title="测试来源",
        excerpt="测试摘录",
        confidence=1.0,
    )


@pytest.fixture
def sample_state():
    """示例 AgentState（最小可用状态）"""
    return {
        "target_product": "Notion",
        "analysis_dimensions": ["功能", "定价"],
        "source_pool": [],
        "competitor_profiles": [],
        "feature_matrix": None,
        "market_insights": [],
        "report": "",
        "review_result": None,
        "iteration_count": 0,
        "messages": [],
    }
