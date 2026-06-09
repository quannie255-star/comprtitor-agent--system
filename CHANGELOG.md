# Changelog

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
