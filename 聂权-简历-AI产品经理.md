# 聂权

**AI 产品经理实习生 | Multi-Agent 架构 · 数据驱动 · 工程落地**

📞 137-9107-2007 | 📧 niequan2024@ruc.edu.cn | 🐙 [github.com/quannie255-star](https://github.com/quannie255-star)  
📍 北京 | 🗓️ 6月下旬到岗，每周5天

---

## 教育背景

**中国人民大学** | 数据科学与大数据技术（理学学士） | 2024.09 - 2028.06

数学分析(91)、人工智能与Python(87) | 美赛M奖（前10%）· 统计建模大赛二等奖 · 大创国家级立项（负责人）

---

## 核心竞争力

- **Multi-Agent 产品落地：** 独立完成 2 个差异化 Multi-Agent 系统从 0 到 1——一个是 LangGraph 驱动的自动化分析引擎，一个是 asyncio MessageBus 驱动的代码审查协作中枢。两个项目架构范式不同、产品定位互补，共沉淀 479 条测试。
- **Agent 架构设计：** 同时实践过两种编排范式——LangGraph DAG（条件路由、反馈闭环）和 asyncio MessageBus（异步消息驱动、SSE 实时推送），理解各自的适用边界。
- **数据驱动与评测：** 擅长 Python + SQL 分析，搭建 Eval 体系，用准确率、可用率、Token 成本、DORA 指标等量化数据驱动决策。
- **AI Native 交付：** Vibe Coding 模式下 Plan-and-Execute 工作流，项目周期从周级压缩至天级，沉淀 [Vibecoding 工程手册](https://github.com/quannie255-star/comprtitor-agent--system/blob/master/VIBECODING_PLAYBOOK.md) 记录 20+ LLM 踩坑经验。

---

## 项目经历

### AgentHub — AI 代码审查协作中枢
**独立开发** | 2026.04 - 至今 | [github.com/quannie255-star/AgentHub](https://github.com/quannie255-star/AgentHub)

> 和 Cursor/Claude Code 不同，AgentHub 不是通用 AI 聊天工具，而是**编排多个 Agent 协同完成代码审查**的协作中枢。提交 PR → Claude（架构+安全）+ Codex（实现+测试）双轨并行审查 → 合并去重 → 六维评分 → 质量门禁 → 讨论修复。

- **多 Agent 双轨编排**：自研 PR 智能路由（按变更规模、文件类型、影响范围自动选择审查 Agent 组合），Claude + Codex 并行审查后按 (文件+分类+标题) 去重合并，支持 @mention 覆盖自动决策。
- **质量门禁与指标体系**：三层判定（通过 / 自动批准 / 失败路由）+ DORA 核心四指标 + AgentHub 专属七指标（AI 覆盖率、检出率、采纳率、时间节省、多 Agent 增益、负载均衡、成本），Mock 模式无 API Key 完整运行。
- **审查协作讨论区**：审查报告底部内嵌讨论面板，支持 `@claude fix`、`@codex test`、`@all re-review`、`@claude explain` 四种审查指令，讨论历史绑定 review 上下文。
- **工程规范**：306 条测试全绿，28 个 Pydantic V2 Schema，FastAPI + SSE 实时推送，asyncio MessageBus 异步消息总线，Repository 模式（aiosqlite），Docker 双容器 + GitHub Actions 4-job CI。

### AI 驱动的自动化分析引擎
**独立开发** | 2026.04 - 至今 | [github.com/quannie255-star/comprtitor-agent--system](https://github.com/quannie255-star/comprtitor-agent--system)

> 基于 LangGraph 的 4-Agent 分析引擎。核心壁垒不是"生成报告"，而是**全链路溯源**——报告中每条结论都可追溯到原始信源 URL + 摘录 + 置信度。支持 4 种分析类型共用同一套 Pipeline。

- **多分析类型平台化**：Collector 按分析类型切换搜索策略（竞品→官网/G2，市场调研→行业报告/新闻，技术选型→GitHub/StackShare，文档审计→站点抓取），Analyst 和 Writer 按类型切换 Prompt 模板和报告结构，一个 Pipeline 支持 4 种场景。
- **全链路溯源体系**：Evidence → AnnotatedFinding 字段级溯源模型，形成"报告结论 → 引用标注 → Agent 执行轨迹 → 原始采集信源" 4 层可逆向验证链路，每条结论绑定信源 URL + 摘录 + 置信度。
- **反馈闭环与可观测性**：LangGraph StateGraph DAG 编排 + 3 种 RejectReason 条件路由 + 质检驳回自动回退重跑（最多 3 轮）。自研 LLMTracer / CostTracker / AuditLogger / Guardrails 可观测性体系，支持 OpenAI / DeepSeek / Anthropic 多 LLM 统一调用。
- **工程规范**：173 条测试覆盖正常 + 降级路径，30+ Pydantic V2 Schema，Docker 一键部署，GitHub Actions CI/CD，[ARCHITECTURE.md](https://github.com/quannie255-star/comprtitor-agent--system/blob/master/ARCHITECTURE.md) 含 3 个 ADR。

### 异构算力协同调度平台（大创国家级立项）
**负责人** | 2026.03 - 至今 | [github.com/quannie255-star](https://github.com/quannie255-star)

- 访谈 3 个实验室，定位 K8s 插件形态降低接入成本，部署时长从 1 天缩短至 10 分钟，预期算力利用率提升 20%。
