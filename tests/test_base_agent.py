"""
Agent 基类与消息总线单元测试

覆盖：
1. MessageBus 订阅/发布/广播
2. BaseAgent 工具注册
3. BaseAgent 消息发送
4. BaseAgent 执行日志
5. 端到端：两个 Agent 通过 MessageBus 通信
"""


from agents.base import BaseAgent, Tool
from core.message_bus import Message, MessageType

# ============================================================
# MessageBus
# ============================================================

class TestMessageBus:
    def test_subscribe_and_publish(self, message_bus):
        received = []

        def handler(msg: Message):
            received.append(msg)

        message_bus.subscribe("analyst", handler)
        msg = Message(
            trace_id="t1",
            sender="collector",
            receiver="analyst",
            msg_type=MessageType.DATA_OUTPUT,
            payload={"data": "test"},
        )
        message_bus.publish(msg)

        assert len(received) == 1
        assert received[0].sender == "collector"
        assert received[0].payload["data"] == "test"

    def test_broadcast_when_no_exact_receiver(self, message_bus):
        received = []

        def handler(msg: Message):
            received.append(msg)

        message_bus.subscribe_broadcast(handler)

        # 发送给未注册的 receiver → 走广播
        msg = Message(
            trace_id="t2",
            sender="collector",
            receiver="nobody",  # 没有人注册
            msg_type=MessageType.TASK_START,
            payload={},
        )
        message_bus.publish(msg)

        assert len(received) == 1

    def test_exact_before_broadcast(self, message_bus):
        """精确匹配优先于广播"""
        exact_received = []
        broadcast_received = []

        message_bus.subscribe("writer", lambda m: exact_received.append(m))
        message_bus.subscribe_broadcast(lambda m: broadcast_received.append(m))

        msg = Message(
            trace_id="t3",
            sender="analyst",
            receiver="writer",
            msg_type=MessageType.DATA_OUTPUT,
            payload={},
        )
        message_bus.publish(msg)

        assert len(exact_received) == 1
        assert len(broadcast_received) == 0  # 精确匹配后不广播

    def test_message_log(self, message_bus):
        msg1 = Message(
            trace_id="t4",
            sender="a",
            msg_type=MessageType.TASK_START,
            payload={},
        )
        msg2 = Message(
            trace_id="t4",
            sender="a",
            msg_type=MessageType.TASK_COMPLETE,
            payload={},
        )
        message_bus.publish(msg1)
        message_bus.publish(msg2)

        log = message_bus.get_message_log()
        assert len(log) == 2

        starts = message_bus.get_messages_by_type(MessageType.TASK_START)
        assert len(starts) == 1

    def test_unsubscribe(self, message_bus):
        received = []

        def handler(msg: Message):
            received.append(msg)

        message_bus.subscribe("analyst", handler)
        message_bus.unsubscribe("analyst")

        msg = Message(
            trace_id="t5",
            sender="collector",
            receiver="analyst",
            msg_type=MessageType.DATA_OUTPUT,
            payload={},
        )
        message_bus.publish(msg)
        assert len(received) == 0  # 已注销

    def test_trace_id_injection(self, message_bus):
        """消息未带 trace_id 时，总线自动注入"""
        received = []

        def handler(msg: Message):
            received.append(msg)

        message_bus.subscribe_broadcast(handler)

        msg = Message(
            sender="collector",
            receiver="analyst",
            msg_type=MessageType.DATA_OUTPUT,
            payload={},
        )  # 未设 trace_id
        message_bus.publish(msg)

        assert received[0].trace_id == message_bus.trace_id


# ============================================================
# 具体 Agent 子类（仅用于测试）
# ============================================================

class _MockCollectorAgent(BaseAgent):
    """测试用 Agent：模拟采集"""

    def execute(self, state: dict, **kwargs) -> dict:
        started = self._log_step(
            action="collect_data",
            input_summary=f"采集目标: {state.get('target_product', 'unknown')}",
            output_summary="模拟采集完成",
            evidence_refs=["src_test"],
        )
        return {"source_pool": [{"url": "https://example.com", "title": "Mock"}]}


# ============================================================
# BaseAgent
# ============================================================

class TestBaseAgent:
    def test_register_tool(self, message_bus):
        agent = _MockCollectorAgent(name="collector", message_bus=message_bus)

        def dummy_search(query: str) -> str:
            return f"搜索结果: {query}"

        tool = Tool(name="web_search", description="搜索网络", func=dummy_search)
        agent.register_tool(tool)

        assert "web_search" in agent.tools
        assert len(agent.get_tools()) == 1

    def test_send_message(self, message_bus):
        agent = _MockCollectorAgent(name="collector", message_bus=message_bus)
        msg = agent.send_message(
            receiver="analyst",
            msg_type=MessageType.DATA_OUTPUT,
            payload={"competitor": "Notion"},
            trace_id="test-trace-002",
        )
        assert msg.sender == "collector"
        assert msg.receiver == "analyst"
        assert msg.payload["competitor"] == "Notion"

        # 消息已进入总线日志
        log = message_bus.get_message_log()
        assert len(log) == 1

    def test_execute_and_log(self, message_bus, sample_state):
        agent = _MockCollectorAgent(name="collector", message_bus=message_bus)
        result = agent.execute(sample_state)

        assert "source_pool" in result
        assert len(agent.get_execution_log()) == 1
        step = agent.get_execution_log()[0]
        assert step["agent_name"] == "collector"
        assert step["action"] == "collect_data"
        assert "src_test" in step["evidence_refs"]

    def test_llm_placeholder(self, message_bus):
        """LLM 未注入时返回占位输出"""
        agent = _MockCollectorAgent(name="collector", message_bus=message_bus)
        result = agent._invoke_llm("测试提示词")
        # 无 LLM 时返回占位字符串
        assert isinstance(result, str)
        assert "占位输出" in result

    def test_agent_name_default(self, message_bus):
        agent = _MockCollectorAgent(name="collector", message_bus=message_bus)
        assert agent.agent_name == "collector"


# ============================================================
# 集成：两个 Agent 通过 MessageBus 通信
# ============================================================

class TestAgentCommunication:
    def test_collector_to_analyst_flow(self, message_bus):
        """模拟 Collector → Analyst 消息流"""
        collector = _MockCollectorAgent(name="collector", message_bus=message_bus)
        analyst_received = []

        # Analyst 订阅自己的消息
        def analyst_handler(msg: Message):
            analyst_received.append(msg)

        message_bus.subscribe("analyst", analyst_handler)

        # Collector 执行任务
        state = {
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
        result = collector.execute(state)

        # Collector 发送结果给 Analyst
        collector.send_message(
            receiver="analyst",
            msg_type=MessageType.DATA_OUTPUT,
            payload={"source_pool": result.get("source_pool", [])},
            trace_id="test-flow-001",
        )

        # Analyst 收到了消息
        assert len(analyst_received) == 1
        assert analyst_received[0].sender == "collector"
        assert "source_pool" in analyst_received[0].payload

    def test_review_feedback_loop(self, message_bus):
        """模拟 Reviewer → Writer 反馈闭环"""
        reviewer_agent = _MockCollectorAgent(name="reviewer", message_bus=message_bus)
        writer_received = []

        def writer_handler(msg: Message):
            writer_received.append(msg)

        message_bus.subscribe("writer", writer_handler)

        # Reviewer 发送质检反馈给 Writer
        reviewer_agent.send_message(
            receiver="writer",
            msg_type=MessageType.REVIEW_FEEDBACK,
            payload={
                "passed": False,
                "reject_reason": "quality_issue",
                "issues": ["SWOT 分析章节缺失"],
            },
            trace_id="test-review-001",
        )

        assert len(writer_received) == 1
        assert writer_received[0].msg_type == MessageType.REVIEW_FEEDBACK
        assert writer_received[0].payload["passed"] is False


# ============================================================
# Tool
# ============================================================

class TestTool:
    def test_create_tool(self):
        def dummy(x: str) -> str:
            return x.upper()

        tool = Tool(name="upper", description="转大写", func=dummy)
        assert tool.name == "upper"
        assert tool.func("hello") == "HELLO"

    def test_to_langchain_tool(self):
        def dummy(x: str) -> str:
            return x

        tool = Tool(name="test", description="测试工具", func=dummy)
        lc_tool = tool.to_langchain_tool()
        assert lc_tool["name"] == "test"
        assert "description" in lc_tool
        assert "func" in lc_tool
