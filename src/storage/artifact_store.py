"""
中间产物持久化

将每个 Agent 的中间输出保存为 JSON 文件，
按 trace_id 组织，支撑分析过程的回溯和调试。
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from loguru import logger


class ArtifactStore:
    """中间产物存储

    保存内容：
      - CompetitorProfile (collector 输出)
      - FeatureMatrix (analyst 输出)
      - MarketInsight[] (analyst 输出)
      - StructuredReport (writer 输出)
      - ReviewResult (reviewer 输出)

    目录结构：
      artifacts/{trace_id}/
        ├── 01_collector_profiles.json
        ├── 02_analyst_feature_matrix.json
        ├── 03_analyst_market_insights.json
        ├── 04_writer_report.json
        └── 05_reviewer_result.json
    """

    def __init__(self, base_dir: str = "./artifacts"):
        self.base_dir = Path(base_dir)

    def save_artifact(
        self,
        trace_id: str,
        stage: str,
        data: Any,
        filename: Optional[str] = None,
    ) -> str:
        """保存中间产物

        Args:
            trace_id: 全链路追踪 ID
            stage: 产物阶段（如 "01_collector", "02_analyst"）
            data: 要保存的数据（Pydantic model 或 dict）
            filename: 自定义文件名

        Returns:
            保存的文件路径
        """
        artifact_dir = self.base_dir / trace_id
        os.makedirs(artifact_dir, exist_ok=True)

        fname = filename or f"{stage}.json"
        filepath = artifact_dir / fname

        # 将 Pydantic model 转为 dict
        if hasattr(data, "model_dump"):
            serialized = data.model_dump(mode="json")
        elif isinstance(data, dict):
            serialized = data
        else:
            serialized = str(data)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(serialized, f, ensure_ascii=False, indent=2, default=str)

        logger.debug(f"中间产物已保存: {filepath}")
        return str(filepath)

    def save_state_snapshot(self, trace_id: str, state: dict, step: int) -> str:
        """保存完整 state 快照（用于调试和回溯）"""
        artifact_dir = self.base_dir / trace_id / "snapshots"
        os.makedirs(artifact_dir, exist_ok=True)

        filepath = artifact_dir / f"state_step_{step:02d}.json"
        # 清理不可序列化的字段
        clean_state = {}
        for k, v in state.items():
            try:
                json.dumps(v, default=str)
                clean_state[k] = v
            except (TypeError, ValueError):
                clean_state[k] = str(v)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(clean_state, f, ensure_ascii=False, indent=2, default=str)

        return str(filepath)

    def load_artifact(self, trace_id: str, filename: str) -> Optional[dict]:
        """加载指定产物"""
        filepath = self.base_dir / trace_id / filename
        if not filepath.exists():
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_artifacts(self, trace_id: str) -> list[str]:
        """列出某个 trace 的所有产物"""
        artifact_dir = self.base_dir / trace_id
        if not artifact_dir.exists():
            return []
        return sorted(
            [f.name for f in artifact_dir.glob("*.json") if f.is_file()]
        )
