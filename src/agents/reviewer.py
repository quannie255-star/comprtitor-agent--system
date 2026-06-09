"""
质检 Agent (Reviewer)

职责：
  1. 接收 Writer 输出的完整报告 + 上游中间产物
  2. 执行交叉审查：事实核查、一致性校验、溯源完整性检查、证据置信度评估
  3. 输出 ReviewResult（含 RejectReason），决定 DAG 条件路由走向
  4. 这是反馈闭环的关键节点：
     - INSUFFICIENT_SOURCE → 回 Collector 补充信源
     - SCHEMA_MISMATCH → 回 Analyst 补充分析
     - QUALITY_ISSUE → 回 Writer 修正报告
     - PASSED → 流水线结束

继承自 BaseAgent。
"""

import json
import re
from datetime import datetime
from typing import Any, Optional

from loguru import logger

from agents.base import BaseAgent
from core.message_bus import MessageType
from core.schema import (
    CompetitorProfile,
    FeatureMatrix,
    MarketInsight,
    RejectReason,
    ReviewResult,
)
from models.review import REVIEW_PROMPT, ReviewChecker


class ReviewerAgent(BaseAgent):
    """质检 Agent

    输入: state["report"] + state["competitor_profiles"] + state["feature_matrix"] + state["market_insights"]
    输出: state["review_result"]

    执行流程:
      1. 反序列化所有上游数据
      2. 编程化基础检查（证据完整性、矩阵完整性、报告结构）
      3. LLM 深度交叉审查
      4. 综合判定，生成 ReviewResult
      5. 根据 reject_reason 发送消息到对应 Agent
    """

    def __init__(
        self,
        message_bus=None,
        llm=None,
        config: Optional[dict] = None,
        checker: Optional[ReviewChecker] = None,
    ):
        super().__init__(
            name="reviewer",
            message_bus=message_bus,
            llm=llm,
            config=config,
        )
        self.checker = checker or ReviewChecker()

    def execute(self, state: dict, **kwargs) -> dict:
        """执行质检流程

        Args:
            state: LangGraph AgentState

        Returns:
            更新后的 state 片段
        """
        target = state.get("target_product", "Unknown")
        report_md = state.get("report", "")
        iteration = state.get("iteration_count", 0)

        logger.info(f"[Reviewer] 开始质检: {target} (第 {iteration + 1} 轮)")

        # --- Step 1: 反序列化上游数据 ---
        profiles = self._deserialize_list(state.get("competitor_profiles", []), CompetitorProfile)
        feature_matrix = self._deserialize_single(state.get("feature_matrix"), FeatureMatrix)
        market_insights = self._deserialize_list(state.get("market_insights", []), MarketInsight)

        # --- Step 2: 编程化检查 ---
        p_start = datetime.now()
        self._log_step(action="programmatic_check", input_summary="编程化基础检查")

        all_issues = []
        all_issues.extend(self.checker.check_evidence_completeness(profiles))
        if feature_matrix:
            all_issues.extend(self.checker.check_matrix_completeness(feature_matrix, profiles))

        self._log_step(
            action="programmatic_check",
            output_summary=f"发现 {len(all_issues)} 个基础问题",
            started_at=p_start,
            duration_ms=(datetime.now() - p_start).total_seconds() * 1000,
        )

        # --- Step 3: LLM 深度审查 ---
        l_start = datetime.now()
        self._log_step(action="llm_review", input_summary="LLM 深度交叉审查")

        upstream_data = self._build_upstream_text(profiles, feature_matrix, market_insights)
        review_prompt = REVIEW_PROMPT.format(
            report_content=report_md[:8000],
            upstream_data=upstream_data[:4000],
        )
        llm_output = self._invoke_llm(review_prompt)
        llm_result = self._parse_review_response(llm_output)

        self._log_step(
            action="llm_review",
            output_summary=f"LLM 审查结果: passed={llm_result.get('passed')}, "
                           f"score={llm_result.get('score')}",
            started_at=l_start,
            duration_ms=(datetime.now() - l_start).total_seconds() * 1000,
        )

        # --- Step 4: 合并判定 ---
        merged_issues = all_issues + llm_result.get("issues", [])
        missing_fields = llm_result.get("missing_fields", [])

        # 统计实际信源数量，防止 LLM 误报 insufficient_source
        total_sources = sum(len(p.data_sources) for p in profiles)

        # 如果编程化检查发现严重问题，强制降级评分
        score = llm_result.get("score", 0.8)
        if all_issues:
            score = min(score, 0.6)

        llm_reason = llm_result.get("reject_reason", "passed")

        # 纠正 LLM 误判：信源充足时忽略 insufficient_source
        if llm_reason == "insufficient_source" and total_sources >= 3:
            logger.warning(f"LLM 误报 insufficient_source（实际信源 {total_sources} 条），降级为 schema_mismatch")
            llm_reason = "schema_mismatch"

        passed = llm_result.get("passed", True) and len(all_issues) == 0
        reject_reason = self._determine_reject_reason(
            llm_passed=llm_result.get("passed", True),
            llm_reason=llm_reason,
            has_programmatic_issues=len(all_issues) > 0,
        )

        review_result = ReviewResult(
            passed=passed,
            reject_reason=reject_reason,
            score=score,
            issues=merged_issues,
            suggestions=llm_result.get("suggestions", []),
            missing_fields=missing_fields,
        )

        self._log_step(
            action="review_complete",
            output_summary=f"最终判定: passed={passed}, reason={reject_reason.value}, "
                           f"score={score}, issues={len(merged_issues)}",
            evidence_refs=[e.source_id for p in profiles for e in p.data_sources],
        )

        # --- Step 5: 根据 RejectReason 发送反馈消息 ---
        self._send_feedback(reject_reason, review_result, target, iteration)

        return {
            "review_result": review_result.model_dump(mode="json"),
        }

    # ============================================================
    # 内部方法
    # ============================================================

    def _send_feedback(
        self,
        reason: RejectReason,
        result: ReviewResult,
        target: str,
        iteration: int,
    ) -> None:
        """根据 reject_reason 向对应 Agent 发送反馈消息"""
        routing_map = {
            RejectReason.INSUFFICIENT_SOURCE: "collector",
            RejectReason.SCHEMA_MISMATCH: "analyst",
            RejectReason.QUALITY_ISSUE: "writer",
        }

        if reason == RejectReason.PASSED:
            self.send_message(
                receiver=None,  # 广播：通知全部 Agent 流水线完成
                msg_type=MessageType.TASK_COMPLETE,
                payload={
                    "target_product": target,
                    "score": result.score,
                    "iteration": iteration,
                },
            )
            logger.info(f"[Reviewer] ✅ 质检通过！流水线完成")
            return

        target_agent = routing_map.get(reason, "analyst")
        self.send_message(
            receiver=target_agent,
            msg_type=MessageType.REVIEW_FEEDBACK,
            payload={
                "target_product": target,
                "reject_reason": reason.value,
                "issues": result.issues,
                "suggestions": result.suggestions,
                "missing_fields": result.missing_fields,
                "iteration": iteration,
            },
        )
        logger.info(f"[Reviewer] ❌ 驳回至 {target_agent}: {reason.value}")

    @staticmethod
    def _determine_reject_reason(
        llm_passed: bool,
        llm_reason: str,
        has_programmatic_issues: bool,
    ) -> RejectReason:
        """综合 LLM 判定和编程化检查，确定最终 RejectReason"""
        if llm_passed and not has_programmatic_issues:
            return RejectReason.PASSED

        # 映射 LLM 返回的字符串到枚举
        reason_map = {
            "insufficient_source": RejectReason.INSUFFICIENT_SOURCE,
            "schema_mismatch": RejectReason.SCHEMA_MISMATCH,
            "quality_issue": RejectReason.QUALITY_ISSUE,
            "passed": RejectReason.PASSED,
        }
        if llm_reason in reason_map and not llm_passed:
            return reason_map[llm_reason]

        # 编程化检查有问题的默认判定
        if has_programmatic_issues:
            return RejectReason.SCHEMA_MISMATCH

        return RejectReason.PASSED

    @staticmethod
    def _parse_review_response(response_text: str) -> dict:
        """解析 LLM 返回的审查结果 JSON"""
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        try:
            return json.loads(text, strict=False)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0), strict=False)
            return {"passed": True, "reject_reason": "passed", "score": 0.5, "issues": [], "suggestions": [], "missing_fields": []}

    @staticmethod
    def _build_upstream_text(
        profiles: list[CompetitorProfile],
        feature_matrix: Optional[FeatureMatrix],
        market_insights: list[MarketInsight],
    ) -> str:
        """构建上游数据摘要（供 LLM 事实核查用）"""
        parts = []
        for p in profiles:
            parts.append(f"[{p.name}] {p.description}")
            parts.append(f"  优势: {', '.join(s.content for s in p.strengths)}")
            parts.append(f"  劣势: {', '.join(w.content for w in p.weaknesses)}")
            parts.append(f"  数据源: {len(p.data_sources)} 条")
        if feature_matrix:
            parts.append(f"[功能对比] {feature_matrix.summary}")
        for mi in market_insights:
            parts.append(f"[{mi.competitor_name} 洞察] 定位: {mi.market_position}")
        return "\n".join(parts)

    @staticmethod
    def _deserialize_list(raw: list, model_class) -> list:
        result = []
        for item in (raw or []):
            if isinstance(item, model_class):
                result.append(item)
            elif isinstance(item, dict):
                result.append(model_class(**item))
        return result

    @staticmethod
    def _deserialize_single(raw, model_class):
        if raw is None:
            return None
        if isinstance(raw, model_class):
            return raw
        if isinstance(raw, dict):
            return model_class(**raw)
        return None
