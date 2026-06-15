"""
LLM 审计日志器

记录每次 Agent 的决策过程，用于：
  - 事后审计：谁在什么时候调了什么模型，输入输出是什么
  - 合规检查：确保没有泄露敏感信息
  - 溯源调试：某个结论是怎么来的

集成方式：
  - 通过 Orchestrator 注入到每个 Agent
  - 所有 Agent 共享同一个 AuditLogger 实例
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from loguru import logger


class AuditLogger:
    """LLM 决策审计日志

    记录内容：
      - Agent 每次 execute() 的输入 state 摘要和输出摘要
      - 每个执行步骤（execution_log）
      - LLM 调用链（通过 LLMTracer）

    输出格式：
      audits/{trace_id}/audit.jsonl  — 每行一条审计事件
      audits/{trace_id}/summary.json — 审计摘要
    """

    def __init__(self, audit_dir: str = "./audits", trace_id: str = ""):
        self.audit_dir = Path(audit_dir)
        self.trace_id = trace_id or str(uuid4())
        self.events: list[dict] = []

    def log(
        self,
        *,
        agent_name: str,
        event_type: str,  # "execute_start" | "execute_end" | "llm_call" | "decision" | "warning"
        detail: dict | str = "",
    ) -> None:
        """记录一条审计事件"""
        event = {
            "timestamp": datetime.now().isoformat(),
            "trace_id": self.trace_id,
            "agent": agent_name,
            "event_type": event_type,
            "detail": detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False, default=str),
        }
        self.events.append(event)

    def log_agent_start(self, agent_name: str, state_keys: list[str]) -> None:
        """Agent 开始执行"""
        self.log(agent_name=agent_name, event_type="execute_start",
                 detail={"state_keys": state_keys})

    def log_agent_end(self, agent_name: str, result_keys: list[str], duration_ms: float) -> None:
        """Agent 执行结束"""
        self.log(agent_name=agent_name, event_type="execute_end",
                 detail={"result_keys": result_keys, "duration_ms": round(duration_ms, 1)})

    def log_llm_call(self, agent_name: str, model: str, latency_ms: float, tokens: int, success: bool) -> None:
        """记录 LLM 调用"""
        self.log(agent_name=agent_name, event_type="llm_call",
                 detail={"model": model, "latency_ms": round(latency_ms, 1), "tokens": tokens, "success": success})

    def log_decision(self, agent_name: str, decision: str, reason: str) -> None:
        """记录 Agent 做出的决策（如 Reviewer 的驳回判断）"""
        self.log(agent_name=agent_name, event_type="decision",
                 detail={"decision": decision, "reason": reason})

    def log_warning(self, agent_name: str, message: str) -> None:
        """记录异常/警告"""
        self.log(agent_name=agent_name, event_type="warning", detail=message)

    def save(self) -> str:
        """持久化审计日志到磁盘"""
        audit_dir = self.audit_dir / self.trace_id
        os.makedirs(audit_dir, exist_ok=True)

        # JSONL 格式：每行一个事件
        jsonl_path = audit_dir / "audit.jsonl"
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for event in self.events:
                f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

        # 摘要
        summary_path = audit_dir / "summary.json"
        summary = self._build_summary()
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

        logger.info(f"审计日志已保存: {audit_dir}")
        return str(audit_dir)

    def _build_summary(self) -> dict:
        """构建审计摘要"""
        agents = {}
        llm_calls = 0
        total_tokens = 0

        for e in self.events:
            agent = e["agent"]
            if agent not in agents:
                agents[agent] = {"execute_count": 0, "llm_calls": 0, "warnings": 0}

            if e["event_type"] == "execute_start":
                agents[agent]["execute_count"] += 1
            elif e["event_type"] == "llm_call":
                agents[agent]["llm_calls"] += 1
                llm_calls += 1
            elif e["event_type"] == "warning":
                agents[agent]["warnings"] += 1

        return {
            "trace_id": self.trace_id,
            "total_events": len(self.events),
            "total_llm_calls": llm_calls,
            "agents": agents,
            "generated_at": datetime.now().isoformat(),
        }
