"""
分析 Agent (Analyst)

职责：
  1. 接收 Collector 输出的 CompetitorProfile
  2. 执行 SWOT 分析、功能对比、市场定位、差异化洞察
  3. 输出 FeatureMatrix + MarketInsight
  4. 每条结论绑定 Evidence（字段级溯源）

继承自 BaseAgent，通过消息总线接收上游数据、发送分析结果给下游。
"""

from datetime import datetime

from loguru import logger

from agents.base import BaseAgent
from core.message_bus import MessageType
from core.schema import (
    AgentType,
    CompetitorProfile,
    Evidence,
    FeatureMatrix,
    IssueCategory,
    MarketInsight,
    Priority,
    PullRequest,
    ReviewIssue,
    ReviewScore,
    SWOTItem,
)
from models.feature import DEFAULT_DIMENSIONS, FEATURE_COMPARISON_PROMPT, FeatureAnalyzer
from models.market import MARKET_INSIGHT_PROMPT, MarketInsightBuilder


class AnalystAgent(BaseAgent):
    """分析 Agent

    输入: state["competitor_profiles"]
    输出: state["feature_matrix"] + state["market_insights"]

    执行流程:
      1. 反序列化 CompetitorProfile
      2. LLM 功能对比分析 → FeatureMatrix
      3. LLM 市场洞察分析 → MarketInsight
      4. 汇总结果，发送消息给 Writer
    """

    def __init__(
        self,
        message_bus=None,
        llm=None,
        config: dict | None = None,
    ):
        super().__init__(
            name="analyst",
            message_bus=message_bus,
            llm=llm,
            config=config,
        )
        self.feature_analyzer = FeatureAnalyzer()
        self.market_builder = MarketInsightBuilder()

        # 从 config 读取分析维度
        agent_config = config.get("agents", {}).get("analyst", {}) if config else {}
        self.dimensions = agent_config.get("comparison_dimensions", DEFAULT_DIMENSIONS)

    def execute(self, state: dict, **kwargs) -> dict:
        """执行分析流程

        Args:
            state: LangGraph AgentState

        Returns:
            更新后的 state 片段
        """
        # --- 输入类型检测：PR 数据 → 代码审查模式 ---
        pr_data = state.get("pr_data")
        if pr_data:
            selected = kwargs.get("selected_agents") or state.get("selected_agents")
            return self._execute_code_review(pr_data, selected, state)

        # --- Step 1: 获取竞品数据 ---
        competitor_data = state.get("competitor_profiles", [])
        if not competitor_data:
            raise ValueError("state 中缺少 competitor_profiles，请先运行 CollectorAgent")

        # 反序列化
        profiles = [
            p if isinstance(p, CompetitorProfile) else CompetitorProfile(**p)
            for p in competitor_data
        ]
        targets = state.get("target_products") or [state.get("target_product", "")]
        # 防御：确保是字符串，且不是被错误迭代的字符
        if isinstance(targets, str):
            targets = [targets]
        target = targets[0] if targets else profiles[0].name
        if len(target) < 2:
            logger.warning(f"⚠ 竞品名可能被截断: '{target}' | state.target_product='{state.get('target_product', 'N/A')}' | state.target_products={state.get('target_products', 'N/A')}")
        source_pool_raw = state.get("source_pool", [])
        evidence_list = [
            e if isinstance(e, Evidence) else Evidence(**e)
            for e in source_pool_raw
        ]

        logger.info(f"[Analyst] 开始分析: {target} ({len(profiles)} 个竞品: {[p.name for p in profiles]})")

        # --- Step 2: 功能对比分析 ---
        f_start = datetime.now()
        self._log_step(action="analysis_start", input_summary=f"分析 {len(profiles)} 个竞品")

        comparison_text = self.feature_analyzer.build_comparison_data(profiles)
        competitor_names = [p.name for p in profiles if p.name and p.name != "待确认"][:3]

        if self.llm is None:
            feature_matrix = FeatureMatrix(
                competitors=competitor_names, dimensions=self.dimensions,
                matrix={dim: {name: "待 LLM 分析" for name in competitor_names} for dim in self.dimensions},
                summary=f"{target} 功能对比（LLM 未配置）", evidence_list=evidence_list,
            )
        else:
            prompt = FEATURE_COMPARISON_PROMPT.format(
                competitor_data=comparison_text, dimensions=", ".join(self.dimensions),
            )
            if len(competitor_names) > 1:
                prompt = f"需要对比 {len(competitor_names)} 个竞品: {', '.join(competitor_names)}\n" + prompt
            llm_output = self._invoke_llm(prompt)
            feature_matrix = self.feature_analyzer.build_matrix_from_llm(
                llm_output, competitors=competitor_names, dimensions=self.dimensions, evidence_list=evidence_list,
            )

        # --- Step 3: 市场洞察（快捷模式：不额外调 LLM，从对比数据推断）---
        market_insights = []
        for profile in profiles:
            mi = MarketInsight(
                competitor_name=profile.name,
                swot=SWOTItem(
                    strengths=[s.content for s in profile.strengths[:3]] if profile.strengths else [],
                    weaknesses=[w.content for w in profile.weaknesses[:3]] if profile.weaknesses else [],
                    opportunities=[],
                    threats=[],
                ),
                market_position=f"{profile.category}领域产品" if profile.category else "待分析",
                evidence_list=evidence_list,
            )
            market_insights.append(mi)

        self._log_step(
            action="analysis_complete",
            output_summary=f"矩阵: {len(feature_matrix.dimensions)} 维度, {len(market_insights)} 条洞察",
            evidence_refs=[e.source_id for e in evidence_list],
            started_at=f_start,
            duration_ms=(datetime.now() - f_start).total_seconds() * 1000,
        )

        # --- Step 4: 发送消息给 Writer ---
        self.send_message(
            receiver="writer",
            msg_type=MessageType.DATA_OUTPUT,
            payload={
                "target_product": target,
                "feature_matrix": feature_matrix.model_dump(mode="json"),
                "market_insights_count": len(market_insights),
            },
        )

        return {
            "feature_matrix": feature_matrix.model_dump(mode="json"),
            "market_insights": [mi.model_dump(mode="json") for mi in market_insights],
        }

    # ============================================================
    # Product Line 2: 双轨代码审查
    # ============================================================

    # --- 审查器内部类 ---

    class ArchitectureReviewer:
        """架构审查器 — 使用 Claude Code 审查架构/安全/性能"""

        SPECIALTIES = [
            IssueCategory.ARCHITECTURE,
            IssueCategory.SECURITY,
            IssueCategory.PERFORMANCE,
            IssueCategory.MAINTAINABILITY,
            IssueCategory.BEST_PRACTICE,
        ]
        AGENT_TYPE = AgentType.CLAUDE
        REVIEW_PROMPT = """You are a senior software architect performing a code review.

Review the following pull request for:
1. **Architecture**: Design patterns, API contracts, separation of concerns, SOLID violations
2. **Security**: OWASP Top 10 vulnerabilities, injection risks, auth/authz issues, data exposure
3. **Performance**: N+1 queries, memory leaks, blocking I/O, algorithmic complexity
4. **Maintainability**: Coupling/cohesion, configuration management, error handling patterns
5. **Best Practices**: Industry standards, framework conventions, deprecation usage

## PR Information
- Title: {pr_title}
- Description: {pr_description}
- Files changed: {file_count}
- Total changes: +{additions}/-{deletions}

## Changed Files
{file_list}

## Diff Content
{diff_content}

Output a JSON array of ReviewIssue objects:
```json
[
  {{
    "category": "architecture|security|performance|maintainability|best_practice",
    "priority": "P0|P1|P2|P3",
    "title": "one-line summary",
    "description": "detailed explanation",
    "file_path": "path/to/file",
    "line_number": null,
    "suggested_fix": "actionable fix suggestion",
    "confidence": 0.0-1.0
  }}
]
```
Focus on issues that would block or significantly impact the PR. Be specific and actionable.
"""

    class ImplementationReviewer:
        """实现审查器 — 使用 Codex CLI 审查边界条件/测试覆盖/代码风格"""

        SPECIALTIES = [
            IssueCategory.BUG,
            IssueCategory.TEST_COVERAGE,
            IssueCategory.STYLE,
            IssueCategory.BEST_PRACTICE,
        ]
        AGENT_TYPE = AgentType.CODEX
        REVIEW_PROMPT = """You are a senior software engineer performing a detailed implementation review.

Review the following pull request for:
1. **Bugs**: Null pointer risks, race conditions, off-by-one errors, type mismatches, edge cases
2. **Test Coverage**: Missing unit/integration tests, uncovered edge cases, brittle assertions
3. **Code Style**: Naming conventions, readability, unnecessary complexity, dead code
4. **Error Handling**: Missing error handling, exception swallowing, proper logging

## PR Information
- Title: {pr_title}
- Description: {pr_description}
- Files changed: {file_count}
- Total changes: +{additions}/-{deletions}

## Changed Files
{file_list}

## Diff Content
{diff_content}

Output a JSON array of ReviewIssue objects:
```json
[
  {{
    "category": "bug|test_coverage|style|best_practice",
    "priority": "P0|P1|P2|P3",
    "title": "one-line summary",
    "description": "detailed explanation with edge case reasoning",
    "file_path": "path/to/file",
    "line_number": null,
    "suggested_fix": "concrete code fix or test case",
    "confidence": 0.0-1.0
  }}
]
```
Flag anything that could cause a production incident or regression. Be thorough on edge cases.
"""

    # --- 代码审查主方法 ---

    def review_code(
        self, pr: PullRequest, selected_agents: list[AgentType] | None = None,
    ) -> tuple[list[ReviewIssue], ReviewScore]:
        """并行调用多个审查器，合并去重结果并计算评分

        Args:
            pr: PullRequest 对象
            selected_agents: 选择的 Agent 列表，默认全部

        Returns:
            (去重后的问题列表, 六维评分)
        """
        if selected_agents is None:
            selected_agents = [AgentType.CLAUDE, AgentType.CODEX]

        all_issues: list[ReviewIssue] = []

        for agent_type in selected_agents:
            if agent_type == AgentType.CLAUDE:
                reviewer = self.ArchitectureReviewer()
            elif agent_type == AgentType.CODEX:
                reviewer = self.ImplementationReviewer()
            else:
                logger.warning(f"[Analyst:Code] 未知 Agent 类型: {agent_type}，跳过")
                continue

            issues = self._run_reviewer(pr, reviewer)
            all_issues.extend(issues)
            logger.info(f"[Analyst:Code] {agent_type.value} 发现 {len(issues)} 个问题")

        deduped = self._deduplicate_issues(all_issues)
        score = self._compute_score(deduped, pr)
        logger.info(
            f"[Analyst:Code] 审查完成: {len(all_issues)} -> {len(deduped)} (去重), "
            f"overall={score.overall}"
        )
        return deduped, score

    def _run_reviewer(
        self, pr: PullRequest, reviewer: "ArchitectureReviewer | ImplementationReviewer",
    ) -> list[ReviewIssue]:
        """运行单个审查器，调用 LLM 或使用 mock 结果"""
        # 构建文件列表和 diff 内容
        file_list = "\n".join(
            f"- `{f.path}` (+{f.additions}/-{f.deletions}) [{f.language}]"
            for f in pr.changed_files[:20]
        )
        diff_content = "\n\n".join(
            f"### {f.path}\n```\n{f.diff[:2000]}\n```"
            for f in pr.changed_files[:10] if f.diff
        )
        if not diff_content:
            diff_content = "(no diff content provided)"

        prompt = reviewer.REVIEW_PROMPT.format(
            pr_title=pr.title,
            pr_description=pr.description or "(no description)",
            file_count=len(pr.changed_files),
            additions=pr.total_additions,
            deletions=pr.total_deletions,
            file_list=file_list,
            diff_content=diff_content,
        )

        if self.llm is None:
            return self._mock_review(pr, reviewer)

        llm_output = self._invoke_llm(prompt)
        return self._parse_review_output(llm_output, reviewer)

    @staticmethod
    def _parse_review_output(
        llm_output: str, reviewer: "ArchitectureReviewer | ImplementationReviewer",
    ) -> list[ReviewIssue]:
        """解析 LLM 返回的 JSON 为 ReviewIssue 列表"""
        import json as _json

        # 提取 JSON（可能在 markdown fence 中）
        text = llm_output.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            raw = _json.loads(text)
        except _json.JSONDecodeError:
            try:
                raw = _json.loads(text, strict=False)
            except _json.JSONDecodeError:
                logger.warning(f"[Analyst:Code] LLM 输出无法解析为 JSON，使用 mock")
                return []

        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            return []

        issues = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                issue = ReviewIssue(
                    category=IssueCategory(item.get("category", "best_practice")),
                    priority=Priority(f"P{item.get('priority', 'P2').replace('P', '')}"),
                    title=item.get("title", "Untitled issue"),
                    description=item.get("description", ""),
                    file_path=item.get("file_path", ""),
                    line_number=item.get("line_number"),
                    suggested_fix=item.get("suggested_fix", ""),
                    agent_source=reviewer.AGENT_TYPE,
                    confidence=float(item.get("confidence", 0.5)),
                )
                issues.append(issue)
            except (ValueError, TypeError) as e:
                logger.warning(f"[Analyst:Code] 跳过无效 issue: {e}")
                continue

        return issues

    def _mock_review(
        self, pr: PullRequest, reviewer: "ArchitectureReviewer | ImplementationReviewer",
    ) -> list[ReviewIssue]:
        """Mock 模式：基于 PR 元数据生成合成审查结果（无需 API key）"""
        issues = []
        agent = reviewer.AGENT_TYPE

        # 每个审查器生成 2-3 个不同分类的问题
        if isinstance(reviewer, self.ArchitectureReviewer):
            # 架构审查: 关注安全、架构
            issues.append(ReviewIssue(
                category=IssueCategory.SECURITY,
                priority=Priority.P1_HIGH,
                title="Review input validation in changed endpoints",
                description="New or modified API endpoints should validate all user inputs to prevent injection attacks.",
                file_path=pr.changed_files[0].path if pr.changed_files else "",
                suggested_fix="Add Pydantic validation models for all request bodies.",
                agent_source=agent,
                confidence=0.85,
            ))
            issues.append(ReviewIssue(
                category=IssueCategory.ARCHITECTURE,
                priority=Priority.P2_MEDIUM,
                title="Consider extracting business logic from route handlers",
                description="Route handlers should delegate to service layer for testability and separation of concerns.",
                file_path=pr.changed_files[0].path if pr.changed_files else "",
                suggested_fix="Extract logic into a service class with dependency injection.",
                agent_source=agent,
                confidence=0.80,
            ))
            if pr.total_changes > 100:
                issues.append(ReviewIssue(
                    category=IssueCategory.PERFORMANCE,
                    priority=Priority.P2_MEDIUM,
                    title="Large PR — consider performance impact of batch operations",
                    description=f"PR touches {pr.total_changes} lines across {len(pr.changed_files)} files. Verify no N+1 queries or unnecessary loops were introduced.",
                    suggested_fix="Profile the changed code paths with representative data volumes.",
                    agent_source=agent,
                    confidence=0.70,
                ))

        elif isinstance(reviewer, self.ImplementationReviewer):
            # 实现审查: 关注 Bug、测试覆盖
            issues.append(ReviewIssue(
                category=IssueCategory.BUG,
                priority=Priority.P1_HIGH,
                title="Verify null/None handling for external inputs",
                description="Functions receiving data from external sources (API, DB, user input) should guard against null values.",
                file_path=pr.changed_files[0].path if pr.changed_files else "",
                line_number=42,
                suggested_fix="Add null checks or use Optional typing with explicit None handling.",
                agent_source=agent,
                confidence=0.82,
            ))
            issues.append(ReviewIssue(
                category=IssueCategory.TEST_COVERAGE,
                priority=Priority.P1_HIGH,
                title="Add unit tests for new/modified functions",
                description="Changed code paths should have corresponding test coverage for both happy path and edge cases.",
                file_path=pr.changed_files[-1].path if pr.changed_files else "",
                suggested_fix=f"Add pytest tests covering: normal input, empty input, boundary values, error conditions.",
                agent_source=agent,
                confidence=0.90,
            ))
            if pr.total_changes < 30:
                issues.append(ReviewIssue(
                    category=IssueCategory.STYLE,
                    priority=Priority.P3_LOW,
                    title="Minor: ensure consistent code formatting",
                    description="Run the project's formatter (ruff/black) to ensure consistent style across changed files.",
                    suggested_fix="Run `ruff format` on changed files.",
                    agent_source=agent,
                    confidence=0.65,
                ))

        return issues

    @staticmethod
    def _deduplicate_issues(issues: list[ReviewIssue]) -> list[ReviewIssue]:
        """按 (file_path, category, title) 去重，保留置信度最高的"""
        seen: dict[str, ReviewIssue] = {}
        for issue in issues:
            key = f"{issue.file_path}|{issue.category.value}|{issue.title[:50]}"
            if key not in seen or issue.confidence > seen[key].confidence:
                seen[key] = issue
        return sorted(
            seen.values(),
            key=lambda x: (x.priority.value, -x.confidence),
        )

    @staticmethod
    def _compute_score(issues: list[ReviewIssue], pr: PullRequest) -> ReviewScore:
        """基于问题列表和 PR 特征计算六维评分"""
        # 统计每个分类的问题
        by_cat: dict[IssueCategory, int] = {}
        for issue in issues:
            by_cat[issue.category] = by_cat.get(issue.category, 0) + 1

        critical = sum(1 for i in issues if i.priority == Priority.P0_CRITICAL)
        high = sum(1 for i in issues if i.priority == Priority.P1_HIGH)

        def _dim_score(issue_count: int, penalty: float = 1.0) -> float:
            """将 issue 数量映射为 0-10 分数"""
            if issue_count == 0:
                return 10.0
            return max(0.0, 10.0 - issue_count * penalty)

        # 各维度评分
        arch_issues = by_cat.get(IssueCategory.ARCHITECTURE, 0)
        sec_issues = by_cat.get(IssueCategory.SECURITY, 0) + critical  # critical 加权
        perf_issues = by_cat.get(IssueCategory.PERFORMANCE, 0)
        test_issues = by_cat.get(IssueCategory.TEST_COVERAGE, 0)
        maint_issues = (
            by_cat.get(IssueCategory.MAINTAINABILITY, 0)
            + by_cat.get(IssueCategory.STYLE, 0)
        )

        # PR 规模惩罚：大 PR 天然难以完美审查
        size_penalty = 0.0
        if pr.change_size == "large":
            size_penalty = 1.0
        elif pr.change_size == "medium":
            size_penalty = 0.3

        score = ReviewScore(
            architecture=_dim_score(arch_issues, 1.5) - size_penalty,
            security=_dim_score(sec_issues, 2.0),  # 安全问题惩罚更重
            performance=_dim_score(perf_issues, 1.5) - size_penalty,
            test_coverage=_dim_score(test_issues, 1.5),
            maintainability=_dim_score(maint_issues, 1.0) - size_penalty * 0.5,
        )
        # 边界裁切
        for field in ["architecture", "security", "performance", "test_coverage", "maintainability"]:
            setattr(score, field, max(0.0, min(10.0, getattr(score, field))))
        score.compute_overall()
        return score

    def _execute_code_review(
        self, pr_data: dict, selected_agents: list | None, state: dict,
    ) -> dict:
        """执行代码审查流程（Product Line 2 入口）

        输入: state["pr_data"]
        输出: state 更新（review_issues + review_score）
        """
        logger.info("[Analyst:Code] 启动双轨代码审查")

        pr = PullRequest(**pr_data) if isinstance(pr_data, dict) else pr_data

        # 解析 Agent 选择
        agents = None
        if selected_agents:
            agents = [
                AgentType(a) if isinstance(a, str) else a
                for a in selected_agents
            ]

        # 执行双轨审查
        issues, score = self.review_code(pr, selected_agents=agents)

        # 发送消息
        self.send_message(
            receiver="writer",
            msg_type=MessageType.DATA_OUTPUT,
            payload={
                "mode": "code_review",
                "pr_title": pr.title,
                "issue_count": len(issues),
                "overall_score": score.overall,
            },
        )

        return {
            "review_issues": [i.model_dump(mode="json") for i in issues],
            "review_score": score.model_dump(mode="json"),
        }
