"""
Agent 基类

提供所有 Agent 的通用能力：
  - LLM 调用封装（LangChain）
  - 工具注册与绑定
  - 消息总线集成
  - 执行日志与溯源
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Callable, Optional
from uuid import uuid4

from loguru import logger

from core.message_bus import Message, MessageBus, MessageType


# ============================================================
# 工具定义
# ============================================================

class Tool:
    """Agent 可调用的工具"""

    def __init__(self, name: str, description: str, func: Callable):
        self.name = name
        self.description = description
        self.func = func

    def to_langchain_tool(self) -> dict:
        """转为 LangChain 兼容的工具描述"""
        return {
            "name": self.name,
            "description": self.description,
            "func": self.func,
        }


# ============================================================
# Agent 基类
# ============================================================

class BaseAgent(ABC):
    """Agent 基类

    所有专职 Agent（Collector / Analyst / Writer / Reviewer）继承此类。

    子类需要实现：
      - execute(): 核心执行逻辑
      - agent_name: Agent 名称
    """

    def __init__(
        self,
        name: str,
        message_bus: Optional[MessageBus] = None,
        llm: Optional[Any] = None,  # LangChain ChatModel，后续由工厂创建
        config: Optional[dict] = None,
    ):
        self.name = name
        self.bus = message_bus
        self.llm = llm
        self.config = config or {}
        self.tools: dict[str, Tool] = {}
        self.execution_log: list[dict] = []  # 执行步骤日志

    @property
    def agent_name(self) -> str:
        """Agent 名称（子类可覆盖）"""
        return self.name

    # --- 工具管理 ---

    def register_tool(self, tool: Tool) -> None:
        """注册工具到 Agent"""
        self.tools[tool.name] = tool
        logger.info(f"[{self.agent_name}] 注册工具: {tool.name}")

    def get_tools(self) -> list[Tool]:
        """获取所有已注册工具"""
        return list(self.tools.values())

    # --- 消息通信 ---

    def send_message(
        self,
        receiver: Optional[str],
        msg_type: MessageType,
        payload: dict,
        trace_id: str = "",
    ) -> Message:
        """发送消息到总线"""
        msg = Message(
            sender=self.agent_name,
            receiver=receiver,
            msg_type=msg_type,
            payload=payload,
            trace_id=trace_id,
        )
        if self.bus:
            self.bus.publish(msg)
        logger.info(f"[{self.agent_name}] → {receiver or 'BROADCAST'} | {msg_type.value}")
        return msg

    # --- 执行日志 ---

    def _log_step(
        self,
        action: str,
        input_summary: str = "",
        output_summary: str = "",
        evidence_refs: Optional[list[str]] = None,
        error: Optional[str] = None,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
        duration_ms: float = 0.0,
    ) -> dict:
        """记录执行步骤"""
        step = {
            "step_id": str(uuid4()),
            "agent_name": self.agent_name,
            "action": action,
            "input_summary": input_summary,
            "output_summary": output_summary,
            "evidence_refs": evidence_refs or [],
            "started_at": (started_at or datetime.now()).isoformat(),
            "finished_at": (finished_at or datetime.now()).isoformat(),
            "duration_ms": duration_ms,
            "error": error,
        }
        self.execution_log.append(step)
        return step

    def get_execution_log(self) -> list[dict]:
        """获取完整执行日志"""
        return self.execution_log

    # --- LLM 调用 ---

    def _invoke_llm(self, prompt: str, system_prompt: str = "") -> str:
        """调用 LLM（抽象封装，子类可直接使用）

        当前为占位实现，第 3 步开始会注入真实的 LangChain ChatModel。
        """
        if self.llm is None:
            logger.warning(f"[{self.agent_name}] LLM 未配置，返回占位结果")
            return f"(LLM_PLACEHOLDER:{self.agent_name}) 占位输出 — {prompt[:50]}..."

        # LangChain ChatModel 统一接口
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))

        response = self.llm.invoke(messages)
        return response.content

    # --- 抽象方法 ---

    @abstractmethod
    def execute(self, state: dict, **kwargs) -> dict:
        """执行当前 Agent 的核心逻辑

        Args:
            state: LangGraph AgentState 或部分 state

        Returns:
            更新后的 state 片段（LangGraph 会 merge 到全局状态）
        """
        ...
