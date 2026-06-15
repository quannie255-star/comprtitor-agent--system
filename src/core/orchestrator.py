"""
DAG 编排引擎 (Orchestrator)

基于 LangGraph 的竞品分析流水线编排：
  Collector → Analyst → Writer → Reviewer
                ↑            │
                └── 反馈闭环 ──┘

支持条件路由：Reviewer 根据 RejectReason 决定回退到哪个 Agent。

也提供简单顺序执行器作为 LangGraph 不可用时的 fallback。
"""

from typing import Any
from uuid import uuid4

from loguru import logger

from agents.analyst import AnalystAgent

# Agent imports
from agents.collector import CollectorAgent
from agents.reviewer import ReviewerAgent
from observability.audit import AuditLogger
from observability.guardrails import Guardrails
from observability.tracer import LLMTracer
from agents.writer import WriterAgent
from core.message_bus import MessageBus
from core.schema import AgentState, AgentType, PullRequest
from storage.artifact_store import ArtifactStore
from storage.trace_store import TraceStore

# ============================================================
# Orchestrator
# ============================================================

class Orchestrator:
    """DAG 编排引擎

    职责：
      - 创建并配置全部 Agent
      - 管理 MessageBus、TraceStore、ArtifactStore
      - 执行 DAG 流水线（LangGraph 或顺序 fallback）
      - 处理反馈闭环（质检驳回→重跑）
      - 聚合可观测性数据

    使用方式：
        orchestrator = Orchestrator(config)
        result = orchestrator.run("Notion", ["功能", "定价"])
    """

    def __init__(self, config: dict):
        self.config = config
        self.trace_id = str(uuid4())

        # 基础设施
        self.bus = MessageBus(trace_id=self.trace_id)
        storage_cfg = config.get("storage", {})
        self.trace_store = TraceStore(base_dir=storage_cfg.get("traces_dir", "./traces"))
        self.artifact_store = ArtifactStore(base_dir=storage_cfg.get("artifacts_dir", "./artifacts"))

        # 可观测性
        self.tracer = LLMTracer(trace_id=self.trace_id)
        self.audit = AuditLogger(trace_id=self.trace_id)
        self.guardrails = Guardrails(strict_mode=config.get("agents", {}).get("reviewer", {}).get("strict_mode", True))
        self.cost_tracker = None  # 在 _save_traces 时填充

        # LLM（从配置创建或为 None）
        self.llm = self._create_llm(config.get("llm", {}))

        # Agent 实例
        self.collector = CollectorAgent(
            message_bus=self.bus,
            llm=self.llm,
            config=config,
        )
        self.analyst = AnalystAgent(
            message_bus=self.bus,
            llm=self.llm,
            config=config,
        )
        self.writer = WriterAgent(
            message_bus=self.bus,
            llm=self.llm,
            config=config,
        )
        self.reviewer = ReviewerAgent(
            message_bus=self.bus,
            llm=self.llm,
            config=config,
        )

        # 注入可观测性组件
        for agent in [self.collector, self.analyst, self.writer, self.reviewer]:
            agent._tracer = self.tracer
            agent._audit = self.audit
            agent._guardrails = self.guardrails

    # ============================================================
    # 主入口
    # ============================================================

    def run(
        self,
        target_product: str,
        analysis_dimensions: list[str] | None = None,
        use_langgraph: bool = True,
        target_products: list[str] | None = None,
        analysis_type: str = "competitor",
    ) -> dict:
        """执行完整竞品分析流水线

        Args:
            target_product: 主竞品名称（向后兼容）
            analysis_dimensions: 分析维度列表
            use_langgraph: 是否使用 LangGraph（False 则用顺序 fallback）
            target_products: 多竞品列表（可选，为空时用 [target_product]）
            analysis_type: 分析类型 (competitor/market_research/tech_evaluation/doc_audit)

        Returns:
            最终 AgentState
        """
        products = target_products or [target_product]
        dimensions = analysis_dimensions or ["核心功能", "定价", "用户体验", "技术架构", "市场定位"]
        logger.info(f"[Orchestrator] 启动流水线: {products} (共 {len(products)} 个), type={analysis_type}, trace={self.trace_id}")

        if use_langgraph:
            try:
                return self._run_with_langgraph(products, dimensions, analysis_type)
            except Exception as e:
                logger.warning(f"LangGraph 执行失败: {e}，降级为顺序执行")
                return self._run_sequential(products, dimensions, analysis_type)
        else:
            return self._run_sequential(products, dimensions, analysis_type)

    # ============================================================
    # Product Line 2: 代码审查入口
    # ============================================================

    def review_pr(
        self,
        pr_data: dict,
        selected_agents: list[str] | None = None,
        use_langgraph: bool = False,
    ) -> dict:
        """执行完整代码审查流水线

        Args:
            pr_data: PR 数据 dict（title, description, changed_files 等）
            selected_agents: 手动指定的 Agent 列表，如 ["claude", "codex"]
                             为 None 时自动路由
            use_langgraph: 是否使用 LangGraph DAG（默认顺序执行）

        Returns:
            最终 state dict（含 report, review_result, dora_metrics 等）
        """
        # 解析 Agent 选择（支持 @mention 语义：@claude / @codex / @all）
        agents = self.route_pr(pr_data, selected_agents)
        logger.info(
            f"[Orchestrator:Code] 启动代码审查: {pr_data.get('title', 'Untitled')}, "
            f"agents={[a.value for a in agents]}"
        )
        return self._run_code_review(pr_data, agents)

    def route_pr(
        self,
        pr_data: dict,
        selected_agents: list[str] | None = None,
    ) -> list[AgentType]:
        """根据 PR 特征自动选择审查 Agent 组合

        路由规则：
          - @mention 覆盖：selected_agents=["claude"] → 只用 Claude
          - 变更 < 50 行 → 轻量审查（Codex 单 Agent）
          - 50-200 行 → 标准审查（Claude + Codex）
          - > 200 行 → 深度审查（Claude + Codex）
          - 配置文件变更 → 侧重格式和一致性（Codex）
          - 源码变更 → 侧重架构和实现（Claude）
          - 测试文件 → 侧重覆盖率（Codex）

        Returns:
            选定的 AgentType 列表
        """
        # @mention 覆盖：显式指定的 Agent 优先
        if selected_agents:
            result = []
            for name in selected_agents:
                name_lower = name.lower().strip()
                if name_lower in ("all", "*"):
                    return [AgentType.CLAUDE, AgentType.CODEX]
                try:
                    result.append(AgentType(name_lower))
                except ValueError:
                    logger.warning(f"[Orchestrator] 未知 Agent: {name}，使用默认路由")
            if result:
                logger.info(f"[Orchestrator] @mention override: {[a.value for a in result]}")
                return result

        # 自动路由：基于 PR 特征
        pr = PullRequest(**pr_data) if isinstance(pr_data, dict) else pr_data
        total = pr.total_changes
        changed_files = pr.changed_files

        # 判断文件类型倾向
        source_files = [
            f for f in changed_files
            if f.language in ("python", "javascript", "typescript", "go", "rust", "java", "cpp", "c")
        ]
        config_files = [
            f for f in changed_files
            if f.language in ("yaml", "json", "toml", "markdown", "docker", "shell")
        ]
        test_files = [f for f in changed_files if "test" in f.path.lower() or "spec" in f.path.lower()]

        # 规模路由
        if total < 50:
            agents = [AgentType.CODEX]  # 小 PR：轻量审查
        elif total < 200:
            agents = [AgentType.CLAUDE, AgentType.CODEX]  # 标准审查
        else:
            agents = [AgentType.CLAUDE, AgentType.CODEX]  # 大 PR：双轨深度

        # 文件类型微调：纯配置文件 → Codex 为主
        if config_files and not source_files:
            agents = [AgentType.CODEX]

        # 源码 > 50% → 确保 Claude 参与架构审查
        if len(source_files) > len(changed_files) * 0.5 and AgentType.CLAUDE not in agents:
            agents.append(AgentType.CLAUDE)

        logger.info(
            f"[Orchestrator] 自动路由: size={pr.change_size} ({total} lines), "
            f"source={len(source_files)}, config={len(config_files)}, test={len(test_files)} "
            f"→ {[a.value for a in agents]}"
        )
        return agents

    def _run_code_review(
        self, pr_data: dict, agents: list[AgentType],
    ) -> dict:
        """顺序执行代码审查流水线（Collector → Analyst → Writer → Reviewer）"""
        import re

        # 提取 @mention 指令
        description = pr_data.get("description", "")
        mentions = re.findall(r"@(\w+)", description)
        if mentions:
            try:
                agents = [AgentType(m.lower()) for m in mentions if m.lower() in ("claude", "codex")]
                logger.info(f"[Orchestrator] @mention in description: {[a.value for a in agents]}")
            except ValueError:
                pass

        state = {
            "pr_data": pr_data,
            "target_product": pr_data.get("title", "Code Review"),
            "source_pool": [],
            "competitor_profiles": [],
            "feature_matrix": None,
            "market_insights": [],
            "report": "",
            "review_result": None,
            "review_issues": None,
            "review_score": None,
            "dora_metrics": None,
            "agenthub_metrics": None,
            "iteration_count": 0,
            "messages": [],
            "trace_id": self.trace_id,
            "selected_agents": [a.value for a in agents],
        }

        # Step 1: Collector — 代码采集
        logger.info("[Orchestrator:Code] → Collector")
        result = self.collector.execute(state)
        state.update(result)

        # Step 2: Analyst — 双轨审查
        logger.info("[Orchestrator:Code] → Analyst")
        state["selected_agents"] = [a.value for a in agents]
        result = self.analyst.execute(state, selected_agents=[a.value for a in agents])
        state.update(result)

        # Step 3: Writer — 生成报告
        logger.info("[Orchestrator:Code] → Writer")
        result = self.writer.execute(state)
        state.update(result)

        # Step 4: Reviewer — 质量门禁
        logger.info("[Orchestrator:Code] → Reviewer")
        result = self.reviewer.execute(state)
        state.update(result)

        # 保存轨迹
        self._save_traces()

        return state

    # ============================================================
    # LangGraph 模式
    # ============================================================

    def _run_with_langgraph(
        self, products: list[str], dimensions: list[str], analysis_type: str = "competitor",
    ) -> dict:
        """使用 LangGraph StateGraph 执行 DAG 流水线"""
        from langgraph.graph import END, StateGraph

        # 初始化状态
        initial_state = {
            "target_product": products[0],
            "target_products": products if isinstance(products, list) else [products],
            "analysis_dimensions": dimensions,
            "source_pool": [],
            "competitor_profiles": [],
            "feature_matrix": None,
            "market_insights": [],
            "report": "",
            "review_result": None,
            "iteration_count": 0,
            "messages": [],
            "trace_id": self.trace_id,
        }

        # 构建 DAG
        workflow = StateGraph(AgentState)

        # 添加节点
        workflow.add_node("collector", self._collector_node)
        workflow.add_node("analyst", self._analyst_node)
        workflow.add_node("writer", self._writer_node)
        workflow.add_node("reviewer", self._reviewer_node)

        # 设置入口
        workflow.set_entry_point("collector")

        # 添加边
        workflow.add_edge("collector", "analyst")
        workflow.add_edge("analyst", "writer")
        workflow.add_edge("writer", "reviewer")

        # 条件边：Reviewer → 根据 RejectReason 路由
        workflow.add_conditional_edges(
            "reviewer",
            self._route_after_review,
            {
                "collector": "collector",
                "analyst": "analyst",
                "writer": "writer",
                "__end__": END,
            },
        )

        # 编译并执行
        orch_cfg = self.config.get("orchestrator", {})
        recursion_limit = orch_cfg.get("recursion_limit", 25)
        app = workflow.compile()
        result = app.invoke(initial_state, {"recursion_limit": recursion_limit})

        # 保存轨迹
        self._save_traces()

        return result

    # ============================================================
    # 顺序 Fallback 模式
    # ============================================================

    def _run_sequential(
        self, products: list[str], dimensions: list[str], analysis_type: str = "competitor",
    ) -> dict:
        """简单顺序执行 + 反馈闭环（无 LangGraph 依赖）"""
        max_rounds = self.config.get("agents", {}).get("reviewer", {}).get("max_review_rounds", 1)

        state = {
            "target_product": products[0],
            "target_products": products if isinstance(products, list) else [products],
            "analysis_dimensions": dimensions,
            "analysis_type": analysis_type,
            "source_pool": [],
            "competitor_profiles": [],
            "feature_matrix": None,
            "market_insights": [],
            "report": "",
            "review_result": None,
            "iteration_count": 0,
            "messages": [],
            "trace_id": self.trace_id,
        }

        # Step 1: Collect
        logger.info(f"[Orchestrator] → Collector | state.target_products={state.get('target_products')} | type={type(state.get('target_products')).__name__}")
        try:
            result = self.collector.execute(state, target_products=products, analysis_type=state.get("analysis_type", "competitor"))
            state.update(result)
            self.artifact_store.save_artifact(
                self.trace_id, "01_collector",
                {"source_pool": state["source_pool"], "competitor_profiles": state["competitor_profiles"]},
            )
        except Exception as e:
            logger.error(f"[Collector] 执行失败: {e}")
            raise

        # 反馈闭环
        while state["iteration_count"] < max_rounds:
            # Step 2: Analyze
            logger.info(f"[Orchestrator] → Analyst (round {state['iteration_count'] + 1})")
            try:
                result = self.analyst.execute(state)
                state.update(result)
                self.artifact_store.save_artifact(
                    self.trace_id, "02_analyst",
                    {"feature_matrix": state.get("feature_matrix"), "market_insights": state.get("market_insights", [])},
                )
            except Exception as e:
                logger.error(f"[Analyst] 执行失败: {e}")
                raise

            # Step 3: Write
            logger.info("[Orchestrator] → Writer")
            try:
                result = self.writer.execute(state)
                state.update(result)
                self.artifact_store.save_artifact(
                    self.trace_id, "04_writer",
                    {"report_length": len(state.get("report", ""))},
                )
            except Exception as e:
                logger.error(f"[Writer] 执行失败: {e}")
                raise

            # Step 4: Review
            logger.info("[Orchestrator] → Reviewer")
            try:
                result = self.reviewer.execute(state)
                state.update(result)
                state["iteration_count"] += 1
                self.artifact_store.save_artifact(
                    self.trace_id, "05_reviewer",
                    state.get("review_result"),
                )
            except Exception as e:
                logger.error(f"[Reviewer] 执行失败: {e}")
                raise

            # 判定
            review = state.get("review_result", {})
            if isinstance(review, dict) and review.get("passed"):
                logger.info("[Orchestrator] ✅ 质检通过！流水线完成")
                break

            reason = review.get("reject_reason", "passed") if isinstance(review, dict) else "passed"
            logger.warning(f"[Orchestrator] ❌ 驳回: {reason} (round {state['iteration_count']}/{max_rounds})")

            # 根据 reason 回退（下一次循环自动从 Analyst 重新开始）
            # 如果是 insufficient_source，重新跑 Collector
            if reason == "insufficient_source":
                logger.info("[Orchestrator] → Collector (补采信源)")
                result = self.collector.execute(state, target_products=products, analysis_type=state.get("analysis_type", "competitor"))
                # 追加新信源，去重
                existing_urls = {s.get("source_url", "") for s in state.get("source_pool", []) if isinstance(s, dict)}
                new_sources = [s for s in result.get("source_pool", []) if isinstance(s, dict) and s.get("source_url", "") not in existing_urls]
                if new_sources:
                    state["source_pool"].extend(new_sources)
                    state["competitor_profiles"].extend(result.get("competitor_profiles", []))
                    logger.info(f"[Orchestrator] 追加 {len(new_sources)} 条新信源")
                else:
                    logger.info("[Orchestrator] 无新信源，跳过追加")

        # 保存轨迹
        self._save_traces()

        return state

    # ============================================================
    # LangGraph 节点
    # ============================================================

    def _collector_node(self, state: AgentState) -> dict:
        logger.info("[Node] Collector")
        result = self.collector.execute(state, analysis_type=state.get("analysis_type", "competitor"))
        self.artifact_store.save_artifact(
            self.trace_id, "01_collector",
            {"source_pool": result.get("source_pool", []),
             "competitor_profiles": result.get("competitor_profiles", [])},
        )
        return result

    def _analyst_node(self, state: AgentState) -> dict:
        logger.info("[Node] Analyst")
        result = self.analyst.execute(state)
        self.artifact_store.save_artifact(
            self.trace_id, "02_analyst",
            {"feature_matrix": result.get("feature_matrix"),
             "market_insights": result.get("market_insights", [])},
        )
        return result

    def _writer_node(self, state: AgentState) -> dict:
        logger.info("[Node] Writer")
        result = self.writer.execute(state)
        self.artifact_store.save_artifact(
            self.trace_id, "04_writer",
            {"report_length": len(result.get("report", ""))},
        )
        return result

    def _reviewer_node(self, state: AgentState) -> dict:
        logger.info("[Node] Reviewer")
        result = self.reviewer.execute(state)
        self.artifact_store.save_artifact(
            self.trace_id, "05_reviewer",
            result.get("review_result"),
        )
        return result

    @staticmethod
    def _route_after_review(state: AgentState) -> str:
        """LangGraph 条件路由：根据 ReviewResult 决定下一步"""
        review = state.get("review_result", {})
        if isinstance(review, dict):
            passed = review.get("passed", True)
            reason = review.get("reject_reason", "passed")
        elif hasattr(review, "passed"):
            passed = review.passed
            reason = review.reject_reason.value if hasattr(review, "reject_reason") else "passed"
        else:
            passed = True
            reason = "passed"

        if passed:
            return "__end__"

        routing = {
            "insufficient_source": "collector",
            "schema_mismatch": "analyst",
            "quality_issue": "writer",
        }
        return routing.get(reason, "__end__")

    # ============================================================
    # LLM 工厂
    # ============================================================

    @staticmethod
    def _create_llm(llm_config: dict) -> Any | None:
        """从配置创建 LangChain ChatModel"""
        api_key = llm_config.get("api_key", "")
        if not api_key or api_key.startswith("${"):
            logger.warning("LLM API Key 未配置，Agent 将使用占位输出")
            return None

        provider = llm_config.get("provider", "openai")
        model = llm_config.get("model", "gpt-4o")
        api_base = llm_config.get("api_base", "")
        temperature = llm_config.get("temperature", 0.3)
        max_tokens = llm_config.get("max_tokens", 4096)

        try:
            if provider == "openai" or provider == "deepseek":
                from langchain_openai import ChatOpenAI

                kwargs = {
                    "model": model,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "api_key": api_key,
                }
                if api_base:
                    kwargs["base_url"] = api_base

                logger.info(f"LLM 已初始化: {provider}/{model}")
                return ChatOpenAI(**kwargs)

            elif provider == "anthropic":
                from langchain_anthropic import ChatAnthropic

                logger.info(f"LLM 已初始化: anthropic/{model}")
                return ChatAnthropic(
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    api_key=api_key,
                )
        except ImportError as e:
            logger.error(f"缺少 LangChain 依赖: {e}")
            return None
        except Exception as e:
            logger.error(f"LLM 初始化失败: {e}")
            return None

        logger.warning(f"未知 LLM provider: {provider}")
        return None

    # ============================================================
    # 可观测性
    # ============================================================

    def _save_traces(self) -> None:
        """保存完整执行轨迹"""
        agent_logs = {
            "collector": self.collector.get_execution_log(),
            "analyst": self.analyst.get_execution_log(),
            "writer": self.writer.get_execution_log(),
            "reviewer": self.reviewer.get_execution_log(),
        }
        msg_log = [m.model_dump(mode="json") for m in self.bus.get_message_log()]

        self.trace_store.save_trace(
            trace_id=self.trace_id,
            agent_logs=agent_logs,
            message_log=msg_log,
            state_summary={
                "target_product": self.trace_id,
                "total_iterations": sum(len(log) for log in agent_logs.values()),
            },
        )
        # 保存 LLM 调用链 + 审计日志
        self.audit.save()

        # 计算成本
        from observability.cost import CostTracker
        self.cost_tracker = CostTracker()
        for span in self.tracer.spans:
            self.cost_tracker.record(span)
        cost_summary = self.cost_tracker.summary()

        logger.info(f"[Orchestrator] 轨迹已保存: traces/{self.trace_id}/, "
                     f"成本: ${cost_summary.get('total_cost', 0):.4f}")

    def get_summary(self) -> dict:
        """获取执行摘要（含 LLM 可观测性）"""
        tracer_summary = self.tracer.summary() if getattr(self, 'tracer', None) else {}
        cost_summary = self.cost_tracker.summary() if getattr(self, 'cost_tracker', None) and self.cost_tracker else {}
        return {
            "trace_id": self.trace_id,
            "collector_steps": len(self.collector.get_execution_log()),
            "analyst_steps": len(self.analyst.get_execution_log()),
            "writer_steps": len(self.writer.get_execution_log()),
            "reviewer_steps": len(self.reviewer.get_execution_log()),
            "messages": len(self.bus.get_message_log()),
            "llm_calls": tracer_summary.get("total_calls", 0),
            "llm_tokens": tracer_summary.get("total_tokens", 0),
            "llm_avg_latency_ms": tracer_summary.get("avg_latency_ms", 0),
            "llm_cost": cost_summary.get("total_cost", 0),
            "llm_savings_vs_gpt4o": cost_summary.get("vs_gpt4o_savings_pct", "N/A"),
        }
