"""
Agent 间消息总线

基于事件驱动的发布/订阅模型，实现 Agent 间标准化通信。
所有消息携带 trace_id，确保全链路可观测。
"""

from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ============================================================
# 消息模型
# ============================================================

class MessageType(str, Enum):
    """消息类型枚举"""

    # 控制消息
    TASK_START = "task_start"          # 任务开始
    TASK_COMPLETE = "task_complete"    # 任务完成
    TASK_FAILED = "task_failed"        # 任务失败

    # 数据消息
    DATA_OUTPUT = "data_output"        # Agent 产出数据
    DATA_REQUEST = "data_request"      # 请求上游数据

    # 反馈消息
    REVIEW_FEEDBACK = "review_feedback"  # 质检反馈（触发重跑）


class Message(BaseModel):
    """标准化消息"""

    id: str = Field(default_factory=lambda: str(uuid4()), description="消息唯一 ID")
    trace_id: str = Field(default="", description="全链路追踪 ID（可由 MessageBus 自动注入）")
    sender: str = Field(description="发送方 Agent 名称")
    receiver: Optional[str] = Field(default=None, description="接收方 Agent 名称（None 表示广播）")
    msg_type: MessageType = Field(description="消息类型")
    payload: dict[str, Any] = Field(default_factory=dict, description="消息体")
    timestamp: datetime = Field(default_factory=datetime.now, description="发送时间")


# ============================================================
# 消息总线
# ============================================================

Handler = Callable[[Message], None]


class MessageBus:
    """事件驱动的 Agent 间消息总线

    职责：
      - 注册/注销消息处理器
      - 按 receiver 或 msg_type 路由消息
      - 记录所有消息流向日志（溯源）

    使用方式：
        bus = MessageBus(trace_id="...")
        bus.subscribe("analyst", handle_analyst_msg)
        bus.publish(Message(sender="collector", receiver="analyst", ...))
    """

    def __init__(self, trace_id: str = ""):
        self.trace_id = trace_id or str(uuid4())
        # 精确匹配处理器: {receiver_name: handler}
        self._exact_handlers: dict[str, Handler] = {}
        # 广播处理器: [handler]（receiver=None 的消息送达此处）
        self._broadcast_handlers: list[Handler] = []
        # 消息日志（全量记录，支撑溯源）
        self.message_log: list[Message] = []

    # --- 订阅 ---

    def subscribe(self, receiver: str, handler: Handler) -> None:
        """订阅：注册对某个 receiver 的处理器"""
        self._exact_handlers[receiver] = handler

    def subscribe_broadcast(self, handler: Handler) -> None:
        """订阅广播消息"""
        self._broadcast_handlers.append(handler)

    def unsubscribe(self, receiver: str) -> None:
        """注销"""
        self._exact_handlers.pop(receiver, None)

    # --- 发布 ---

    def publish(self, message: Message) -> None:
        """发布消息：路由到匹配的处理器"""
        # 注入 trace_id（如果消息未携带）
        if not message.trace_id:
            message.trace_id = self.trace_id

        self.message_log.append(message)

        # 精确路由
        if message.receiver and message.receiver in self._exact_handlers:
            self._exact_handlers[message.receiver](message)
            return

        # 广播
        for handler in self._broadcast_handlers:
            handler(message)

    # --- 日志 ---

    def get_message_log(self) -> list[Message]:
        """获取完整消息日志（按时间排序）"""
        return sorted(self.message_log, key=lambda m: m.timestamp)

    def get_messages_by_type(self, msg_type: MessageType) -> list[Message]:
        """按类型过滤消息"""
        return [m for m in self.message_log if m.msg_type == msg_type]
