"""
执行轨迹持久化

将每次分析的完整执行轨迹保存为 JSON 文件，
按 trace_id 组织，支撑全链路溯源。
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from loguru import logger


class TraceStore:
    """执行轨迹存储

    保存内容：
      - 每个 Agent 的执行步骤日志
      - 消息总线完整消息日志
      - 时间线摘要

    目录结构：
      traces/{trace_id}/
        ├── timeline.json      # 时间线摘要
        ├── messages.json      # 消息日志
        └── agents/
            ├── collector.json # Collector 执行日志
            ├── analyst.json   # Analyst 执行日志
            ├── writer.json    # Writer 执行日志
            └── reviewer.json  # Reviewer 执行日志
    """

    def __init__(self, base_dir: str = "./traces"):
        self.base_dir = Path(base_dir)

    def save_trace(
        self,
        trace_id: str,
        agent_logs: dict[str, list[dict]],  # {agent_name: [execution_steps]}
        message_log: list[dict],
        state_summary: Optional[dict] = None,
    ) -> str:
        """保存完整执行轨迹

        Args:
            trace_id: 全链路追踪 ID
            agent_logs: 各 Agent 的执行日志
            message_log: 消息总线日志
            state_summary: 最终状态摘要

        Returns:
            轨迹目录路径
        """
        trace_dir = self.base_dir / trace_id
        agents_dir = trace_dir / "agents"
        os.makedirs(agents_dir, exist_ok=True)

        # 保存各 Agent 日志
        for agent_name, steps in agent_logs.items():
            filepath = agents_dir / f"{agent_name}.json"
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(steps, f, ensure_ascii=False, indent=2, default=str)

        # 保存消息日志
        with open(trace_dir / "messages.json", "w", encoding="utf-8") as f:
            json.dump(message_log, f, ensure_ascii=False, indent=2, default=str)

        # 保存时间线摘要
        timeline = self._build_timeline(agent_logs, message_log, state_summary)
        with open(trace_dir / "timeline.json", "w", encoding="utf-8") as f:
            json.dump(timeline, f, ensure_ascii=False, indent=2, default=str)

        logger.info(f"执行轨迹已保存: {trace_dir}")
        return str(trace_dir)

    @staticmethod
    def _build_timeline(
        agent_logs: dict[str, list[dict]],
        message_log: list[dict],
        state_summary: Optional[dict],
    ) -> dict:
        """构建时间线摘要"""
        events = []

        # 从 Agent 日志中提取关键事件
        for agent_name, steps in agent_logs.items():
            for step in steps:
                events.append({
                    "time": step.get("started_at", ""),
                    "agent": agent_name,
                    "action": step.get("action", ""),
                    "summary": step.get("output_summary", "") or step.get("input_summary", ""),
                })

        # 按时间排序
        events.sort(key=lambda e: e["time"])

        return {
            "generated_at": datetime.now().isoformat(),
            "event_count": len(events),
            "message_count": len(message_log),
            "events": events,
            "state_summary": state_summary or {},
        }

    def load_trace(self, trace_id: str) -> Optional[dict]:
        """加载指定 trace 的完整轨迹"""
        trace_dir = self.base_dir / trace_id
        if not trace_dir.exists():
            return None

        result = {"trace_id": trace_id, "agents": {}, "messages": [], "timeline": {}}

        # 加载 Agent 日志
        agents_dir = trace_dir / "agents"
        if agents_dir.exists():
            for f in agents_dir.glob("*.json"):
                agent_name = f.stem
                with open(f, "r", encoding="utf-8") as fh:
                    result["agents"][agent_name] = json.load(fh)

        # 加载消息日志
        msg_file = trace_dir / "messages.json"
        if msg_file.exists():
            with open(msg_file, "r", encoding="utf-8") as f:
                result["messages"] = json.load(f)

        # 加载时间线
        tl_file = trace_dir / "timeline.json"
        if tl_file.exists():
            with open(tl_file, "r", encoding="utf-8") as f:
                result["timeline"] = json.load(f)

        return result
