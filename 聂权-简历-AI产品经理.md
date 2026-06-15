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

- **Multi-Agent 落地全链路：** 从需求、DAG编排、Eval闭环到前端交付，独立完成2个Agent系统从0到1，沉淀 [Vibecoding 工程手册](https://github.com/quannie255-star/comprtitor-agent--system/blob/master/VIBECODING_PLAYBOOK.md)。
- **Agent 架构设计：** 熟练运用 DAG 流转、条件路由、反馈闭环、大小模型路由、Human-in-the-loop 等模式，设计过 3 种 RejectReason 的质检驳回回路。
- **数据驱动与评测：** 擅长 Python + SQL 分析，搭建 Eval 体系，用准确率、可用率、Token 成本等指标驱动决策。
- **AI Native 交付：** Vibe Coding 模式下 Plan-and-Execute 工作流，项目周期从周级压缩至天级，累计编写 400+ 测试用例。

---

## 项目经历

### AgentHub — IM 式多 Agent 协作平台
**独立开发** | 2026.04 - 至今 | [github.com/quannie255-star/AgentHub](https://github.com/quannie255-star/AgentHub)

- 自研 TaskParser 支持编号/逗号/@-mention 三种输入，结合关键词+LLM 双路径路由，Agent 分配准确率从 70% 提升至 90%+，内置 3 次重试+降级策略。
- 设计 FastAPI + SSE 实时流式架构，自研 asyncio.Queue 消息总线，实现双阶段流式渲染（replay + live），避免消息丢失。
- 插件化 Agent 适配：AbstractAgentAdapter 抽象基类 + AdapterRegistry，新增 Agent 类型只需实现 3 个方法。293 条测试全绿，20 个 Pydantic V2 Schema，Docker + GitHub Actions CI/CD。

### AI 驱动的竞品分析 Agent 协作系统
**独立开发** | 2026.04 - 至今 | [github.com/quannie255-star/comprtitor-agent--system](https://github.com/quannie255-star/comprtitor-agent--system)

- 基于 LangGraph 构建 Collector → Analyst → Writer → Reviewer 流水线，质检驳回自动回退重跑（最多 3 轮），同时支持顺序 fallback 保证可用性。
- 双轨质检：Python 硬编码规则（信源/Schema 一致性）+ LLM 语义审查，报告可用率从 60% 提升至 85%+。
- 字段级溯源模型：每条结论绑定信源 URL + 摘录 + 置信度，形成"报告→来源→轨迹→数据"4 层可逆链。自研 LLMTracer/CostTracker/AuditLogger/Guardrails 可观测性体系，130 条测试。

### 异构算力协同调度平台（大创国家级立项）
**负责人** | 2026.03 - 至今 | [github.com/quannie255-star](https://github.com/quannie255-star)

- 访谈 3 个实验室，定位 K8s 插件形态降低接入成本，部署时长从 1 天缩短至 10 分钟，预期算力利用率提升 20%。
