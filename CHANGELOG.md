# Changelog

## [0.2.0] — 2026-06-15

### 新增 — Product Line 2: Code Review

- **双产品线架构**：4-Agent Pipeline 支持竞品分析 + 代码审查两条并行产品线
- **代码采集**：Collector 新增 `collect_from_pr()` / `collect_from_diff()`，自动识别 PR 输入
- **双轨代码审查**：Analyst 新增 ArchitectureReviewer(Claude) + ImplementationReviewer(Codex)，并行审查后去重合并
- **审查报告**：Writer 新增 8 章节 Markdown 审查报告（含评分表、问题列表、证据溯源）
- **质量门禁**：Reviewer 新增三层判定（通过/自动批准/失败路由）+ DORA 四指标 + AgentHub 七指标
- **智能路由**：Orchestrator 新增 `route_pr()`，根据 PR 规模自动选择审查策略（<50 行 → Codex / 50-200 → 双 Agent）
- **Streamlit Tab 2**：Code Review 界面（PR 提交、Agent 选择、评分仪表盘、DORA 面板、报告下载）
- **配置扩展**：`settings.yaml` 新增 `code_review` 块；`agents.yaml` 新增 4 个审查 Agent 角色定义

### Schema 扩展

- 新增 3 个 Enum：`AgentType`、`IssueCategory`、`Priority`
- 新增 7 个 Pydantic Model：`PullRequest`、`FileChange`、`ReviewIssue`、`ReviewScore`、`ReviewReport`、`DORAMetrics`、`AgentHubMetrics`
- `ReviewScore` 含加权评分计算 + `passes_quality_gate()` + `auto_approvable()`
- `ReviewReport` 含 `render_markdown()` 生成完整审查报告
- `DORAMetrics` 含 `performance_level()` 自动分级 + `to_comparison()` 对比表
- `AgentHubMetrics` 含 7 指标汇总 + `to_summary()` 目标对比

### 测试

- 新增 `test_code_review.py`（19 条），覆盖所有新模型 + 端到端 Mock 流水线
- 全量测试 173 条全绿，零回归
- Mock 模式：无 API Key 完整运行

### 工程

- README 更新：双产品线架构图、PL1/PL2 详情、快速开始含 Code Review 示例
- 项目结构树更新，反映新增模块

## [0.1.0] — 2026-06-09

### 新增

- **4 Agent 协作流水线**：Collector（采集）→ Analyst（分析）→ Writer（撰写）→ Reviewer（质检）
- **DAG 编排引擎**：LangGraph StateGraph + 顺序 fallback 模式
- **条件路由反馈闭环**：3 种 RejectReason（insufficient_source / schema_mismatch / quality_issue）→ 自动回退对应 Agent
- **字段级溯源**：AnnotatedFinding 绑定 Evidence（source_url + excerpt + confidence）
- **多竞品横向对比**：支持 1-3 个竞品同时分析，生成对比矩阵
- **Streamlit 前端**：卡片化布局、目录导航、溯源高亮、一键下载 Markdown
- **Docker 一键部署**：`docker-compose up` 即可访问
- **GitHub Actions CI**：push 自动运行 130 条测试 + ruff lint + mypy 类型检查
- **可观测性基础设施**：TraceStore（执行轨迹）+ ArtifactStore（中间产物）+ MessageBus（消息日志）
- **多 LLM 支持**：OpenAI / DeepSeek / Anthropic，统一 LangChain 调用层

### 工程规范

- 130 条单元 + 集成测试，覆盖率 74%
- pre-commit hooks（ruff + mypy）
- `.gitignore`、`.dockerignore`、`LICENSE`（MIT）
- 3 份文档：使用手册、升级手册、面试备战手册
- ARCHITECTURE.md（Mermaid 架构图 + 3 ADR）
