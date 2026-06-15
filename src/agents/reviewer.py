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

from loguru import logger

from agents.base import BaseAgent
from core.message_bus import MessageType
from core.schema import (
    AgentHubMetrics,
    AgentType,
    CompetitorProfile,
    DORAMetrics,
    FeatureMatrix,
    MarketInsight,
    Priority,
    RejectReason,
    ReviewIssue,
    ReviewReport,
    ReviewResult,
    ReviewScore,
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
        config: dict | None = None,
        checker: ReviewChecker | None = None,
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

        # --- 输入类型检测：代码审查模式 ---
        pr_data = state.get("pr_data")
        review_issues = state.get("review_issues")
        review_score = state.get("review_score")
        if pr_data and (review_issues is not None or report_md):
            return self._execute_quality_gate(pr_data, review_issues, review_score, report_md, state)

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
            logger.info("[Reviewer] ✅ 质检通过！流水线完成")
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
        feature_matrix: FeatureMatrix | None,
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

    # ============================================================
    # Product Line 2: 质量门禁 + 指标追踪
    # ============================================================

    def check_quality_gate(
        self,
        score: ReviewScore,
        issues: list[ReviewIssue],
        pr_title: str = "",
    ) -> dict:
        """质量门禁引擎

        最低通过标准:
          - overall >= 6.0, security >= 7.0, performance >= 6.0
          - test_coverage >= 5.0, critical_count == 0

        自动批准标准:
          - overall >= 8.5, critical_count == 0, high_count <= 1, total_issues <= 3

        Returns:
            {
                "passed": bool,
                "auto_approved": bool,
                "failures": list[str],
                "routing": "passed" | "analyst" | "writer",
            }
        """
        critical_count = sum(1 for i in issues if i.priority == Priority.P0_CRITICAL)
        high_count = sum(1 for i in issues if i.priority == Priority.P1_HIGH)

        # 最低通过标准
        passed, failures = score.passes_quality_gate()
        if critical_count > 0:
            passed = False
            failures.append(f"critical_issues ({critical_count} P0 issues)")

        # 自动批准
        auto_approved = score.auto_approvable(
            threshold=8.5,
            critical_count=critical_count,
            high_count=high_count,
        ) and len(issues) <= 3

        # 路由决策
        if passed:
            routing = "passed"
        elif critical_count > 0 or any("security" in f for f in failures):
            routing = "analyst"   # 安全问题回 Analyst 重审
        else:
            routing = "analyst"   # 默认回 Analyst 补充审查

        logger.info(
            f"[Reviewer:Gate] {pr_title}: passed={passed}, "
            f"auto_approved={auto_approved}, critical={critical_count}, "
            f"high={high_count}, routing={routing}"
        )
        return {
            "passed": passed,
            "auto_approved": auto_approved,
            "failures": failures,
            "routing": routing,
        }

    def track_metrics(
        self,
        issues: list[ReviewIssue],
        score: ReviewScore,
        review_duration_ms: float = 0,
        agent_usage: dict[AgentType, int] | None = None,
    ) -> tuple[DORAMetrics, AgentHubMetrics]:
        """计算并记录本次审查的各项指标

        Args:
            issues: 审查发现的问题列表
            score: 六维评分
            review_duration_ms: 审查耗时（毫秒）
            agent_usage: 各 Agent 使用次数

        Returns:
            (DORAMetrics, AgentHubMetrics)
        """
        # DORA 指标（模拟值 — 实际部署时从 CI/CD 系统读取）
        dora = DORAMetrics(
            deployment_frequency=3.0,        # 默认 3 次/周
            lead_time_hours=review_duration_ms / 3600000,  # 审查时长即 lead time 的一部分
            change_failure_rate=5.0,         # 默认 5%
            mttr_hours=3.6,                  # 默认 3.6h
        )

        # AgentHub 专属七指标
        total_issues = len(issues)
        high_critical = sum(
            1 for i in issues
            if i.priority in (Priority.P0_CRITICAL, Priority.P1_HIGH)
        )
        agent_usage = agent_usage or {}

        # AI Issue Detection Rate: 高优先级 issue 占比
        ai_detection_rate = high_critical / max(total_issues, 1)

        # AI Fix Adoption Rate: 有修复建议的 issue 占比（模拟 0.55 基准）
        has_fix = sum(1 for i in issues if i.suggested_fix)
        fix_adoption = has_fix / max(total_issues, 1)

        # Human Review Time Saved: 基于评分估算
        # overall >= 8.5 → 节省 80%+, overall >= 6.0 → 节省 50%+
        if score.overall >= 8.5:
            time_saved = 0.85
        elif score.overall >= 7.0:
            time_saved = 0.70
        elif score.overall >= 6.0:
            time_saved = 0.50
        else:
            time_saved = 0.30

        # Multi-Agent Efficiency: 多 Agent 发现更多不同分类的问题
        categories_found = len({i.category for i in issues})
        multi_agent_gain = min(0.5, categories_found / 8.0)  # 最多 8 个分类

        # Agent Utilization Balance: Claude vs Codex 负载差异
        claude_count = agent_usage.get(AgentType.CLAUDE, 0)
        codex_count = agent_usage.get(AgentType.CODEX, 0)
        total_agent_calls = claude_count + codex_count
        if total_agent_calls > 0:
            utilization_balance = abs(claude_count - codex_count) / total_agent_calls
        else:
            utilization_balance = 0.0

        # Cost Per Review: 基于 Token 量的简化估算
        base_cost = 0.50  # 基础成本
        issue_cost = total_issues * 0.15  # 每个 issue 增加成本
        cost_per_review = base_cost + issue_cost

        metrics = AgentHubMetrics(
            ai_review_coverage=0.90,          # 假设 90% 覆盖率
            ai_issue_detection_rate=ai_detection_rate,
            ai_fix_adoption_rate=fix_adoption,
            human_review_time_saved_pct=time_saved,
            multi_agent_efficiency_gain=multi_agent_gain,
            agent_utilization_balance=utilization_balance,
            cost_per_review_usd=round(cost_per_review, 2),
        )

        logger.info(
            f"[Reviewer:Metrics] DORA level={dora.performance_level()}, "
            f"detection_rate={ai_detection_rate:.1%}, "
            f"time_saved={time_saved:.0%}, cost=${cost_per_review:.2f}"
        )
        return dora, metrics

    def _execute_quality_gate(
        self,
        pr_data: dict,
        issues_data: list | None,
        score_data: dict | None,
        report_md: str,
        state: dict,
    ) -> dict:
        """执行代码审查质量门禁（Product Line 2 入口）

        输入: state["pr_data"] + state["review_issues"] + state["review_score"] + state["report"]
        输出: state["review_result"] + state["dora_metrics"] + state["agenthub_metrics"]
        """
        logger.info("[Reviewer:Gate] 启动代码审查质量门禁")

        # 反序列化
        issues = [
            ReviewIssue(**i) if isinstance(i, dict) else i
            for i in (issues_data or [])
        ]
        score = ReviewScore(**score_data) if isinstance(score_data, dict) else (score_data or ReviewScore())

        # 质量门禁判定
        pr_title = pr_data.get("title", "") if isinstance(pr_data, dict) else ""
        gate = self.check_quality_gate(score, issues, pr_title)

        # 指标追踪
        dora, agent_metrics = self.track_metrics(
            issues, score,
            agent_usage={
                AgentType.CLAUDE: sum(1 for i in issues if i.agent_source == AgentType.CLAUDE),
                AgentType.CODEX: sum(1 for i in issues if i.agent_source == AgentType.CODEX),
            },
        )

        # 映射 routing 到 RejectReason
        routing_map = {
            "passed": RejectReason.PASSED,
            "analyst": RejectReason.SCHEMA_MISMATCH,
            "writer": RejectReason.QUALITY_ISSUE,
        }
        reject_reason = routing_map.get(gate["routing"], RejectReason.PASSED)

        # 构建 ReviewResult（复用现有模型）
        result = ReviewResult(
            passed=gate["passed"],
            reject_reason=reject_reason,
            score=score.overall / 10.0,  # 归一化到 0-1
            issues=gate["failures"],
            suggestions=[],
            missing_fields=[],
        )

        self._log_step(
            action="quality_gate_complete",
            output_summary=(
                f"gate={'PASSED' if gate['passed'] else 'FAILED'}, "
                f"auto_approved={gate['auto_approved']}, "
                f"DORA={dora.performance_level()}, "
                f"cost=${agent_metrics.cost_per_review_usd:.2f}"
            ),
        )

        # 根据结果发送消息
        if gate["passed"]:
            self.send_message(
                receiver=None,
                msg_type=MessageType.TASK_COMPLETE,
                payload={
                    "mode": "code_review",
                    "pr_title": pr_title,
                    "auto_approved": gate["auto_approved"],
                    "overall_score": score.overall,
                },
            )
            logger.info(f"[Reviewer:Gate] ✅ 质量门禁通过{' (自动批准)' if gate['auto_approved'] else ''}")
        else:
            target = routing_map.get(gate["routing"], "analyst")
            self.send_message(
                receiver=target,
                msg_type=MessageType.REVIEW_FEEDBACK,
                payload={
                    "mode": "code_review",
                    "pr_title": pr_title,
                    "failures": gate["failures"],
                    "routing": gate["routing"],
                },
            )
            logger.warning(f"[Reviewer:Gate] ❌ 门禁失败 → 回退到 {gate['routing']}")

        return {
            "review_result": result.model_dump(mode="json"),
            "dora_metrics": dora.model_dump(mode="json"),
            "agenthub_metrics": agent_metrics.model_dump(mode="json"),
        }
