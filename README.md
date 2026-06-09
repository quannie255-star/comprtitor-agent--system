# 🔍 AI 驱动的竞品分析 Agent 协作系统

[![CI](https://github.com/niequan/ai-competitive-analysis/actions/workflows/ci.yml/badge.svg)](https://github.com/niequan/ai-competitive-analysis/actions)
[![Coverage](https://codecov.io/gh/niequan/ai-competitive-analysis/branch/master/graph/badge.svg)](https://codecov.io/gh/niequan/ai-competitive-analysis)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-130%20passed-green.svg)](https://github.com/niequan/ai-competitive-analysis)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](https://github.com/niequan/ai-competitive-analysis/releases)

基于 LangGraph 的多 Agent 协作系统，自动完成从公开信息采集到结构化竞品报告输出的全链路工作。

## 架构概览

```
用户输入 (竞品名称) → Orchestrator (DAG 编排)
                          │
    ┌─────────────────────┼─────────────────────┐
    ▼                     ▼                     ▼
Collector ──────→ Analyst ──────→ Writer ──────→ Reviewer
(搜索+抓取)      (功能对比+SWOT)  (报告生成)      (交叉审查)
    │                ▲                ▲              │
    └── 信源不足 ←──┘                └── 质量问题 ───┘
                        │                (反馈闭环)
                        └── Schema缺失 ──┘
```

**4 个专职 Agent**：
| Agent | 职责 | 输出 |
|---|---|---|
| Collector | 搜索 → 抓取 → LLM 解析 | CompetitorProfile + Evidence |
| Analyst | 功能对比 + SWOT + 市场洞察 | FeatureMatrix + MarketInsight |
| Writer | 报告章节拼装 + Markdown 渲染 | StructuredReport (MD) |
| Reviewer | 事实核查 + 溯源验证 + 评分 | ReviewResult + 条件路由 |

**核心特性**：
- ✅ **DAG 编排** — LangGraph 驱动的有向无环图流水线
- ✅ **反馈闭环** — 质检驳回自动回退到对应 Agent 重跑
- ✅ **全链路溯源** — 每条分析结论绑定 Evidence，可逆向追踪
- ✅ **可观测性** — 执行轨迹、消息日志、中间产物完整记录

## 快速开始

### 1. 安装

**方式 A：Docker 一键启动（推荐）**

```bash
git clone <repo-url>
cd ai-competitive-analysis
cp .env.example .env          # 编辑 .env 填入 API Key（可选）
docker-compose up
```

浏览器访问 `http://localhost:8501`

**方式 B：pip 本地安装**

```bash
git clone <repo-url>
cd ai-competitive-analysis
pip install -e ".[dev]"
```

### 2. 配置

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env，填入 API Key
# LLM_API_KEY=sk-xxx      # OpenAI / DeepSeek
# LLM_API_BASE=https://api.deepseek.com/v1  # 可选
# TAVILY_API_KEY=tvly-xxx # 搜索 API（可选，无 Key 使用 mock）
```

### 3. 运行测试

```bash
pytest tests/ -v
```

### 4. 命令行使用

```bash
python -c "
from core.orchestrator import Orchestrator

config = {
    'llm': {'provider': 'openai', 'model': 'gpt-4o', 'api_key': ''},
    'search': {'api_key': ''},
    'agents': {
        'analyst': {'comparison_dimensions': ['功能', '定价', '体验']},
        'reviewer': {'max_review_rounds': 3},
    },
    'orchestrator': {'recursion_limit': 25},
    'storage': {'traces_dir': './traces', 'outputs_dir': './outputs', 'artifacts_dir': './artifacts'},
}

orchestrator = Orchestrator(config)
result = orchestrator.run('Notion', use_langgraph=False)

# 报告已生成
print(result['report'][:500])

# 查看轨迹
print(f\"Trace: traces/{orchestrator.trace_id}/\")
"
```

### 5. Streamlit 前端

```bash
streamlit run src/api/routes.py
```

浏览器访问 `http://localhost:8501`，输入竞品名称即可开始分析。

## 项目结构

```
ai-competitive-analysis/
├── config/
│   ├── settings.yaml         # 全局配置（LLM、搜索、Agent、编排）
│   └── agents.yaml           # Agent 角色定义与 Prompt 模板
├── src/
│   ├── core/
│   │   ├── schema.py         # 竞品知识 Schema（Pydantic V2）
│   │   ├── message_bus.py    # Agent 间消息总线（发布/订阅）
│   │   └── orchestrator.py   # DAG 编排引擎（LangGraph + 顺序 fallback）
│   ├── agents/
│   │   ├── base.py           # Agent 基类（LLM 封装、工具注册、日志）
│   │   ├── collector.py      # 采集 Agent
│   │   ├── analyst.py        # 分析 Agent
│   │   ├── writer.py         # 撰写 Agent
│   │   └── reviewer.py       # 质检 Agent
│   ├── tools/
│   │   ├── web_search.py     # Tavily 搜索工具
│   │   ├── web_scraper.py    # 网页抓取工具
│   │   └── data_parser.py    # 数据结构化解析
│   ├── models/
│   │   ├── feature.py        # 功能对比分析模型
│   │   ├── market.py         # 市场洞察分析模型
│   │   ├── report.py         # Markdown 报告渲染器
│   │   └── review.py         # 质检审查工具集
│   ├── storage/
│   │   ├── trace_store.py    # 执行轨迹持久化
│   │   └── artifact_store.py # 中间产物持久化
│   └── api/
│       └── routes.py         # Streamlit 前端入口
├── tests/
│   ├── conftest.py           # 共享 Fixtures
│   ├── test_schema.py        # Schema 测试（20 条）
│   ├── test_base_agent.py    # Agent 基类 + 消息总线（15 条）
│   ├── test_collector.py     # 采集 Agent（12 条）
│   ├── test_analyst.py       # 分析 Agent（12 条）
│   ├── test_writer.py        # 撰写 Agent（22 条）
│   ├── test_reviewer.py      # 质检 Agent（27 条）
│   └── test_orchestrator.py  # 端到端集成测试（10 条）
├── outputs/                  # 生成的竞品报告
├── traces/                   # 执行轨迹日志
├── artifacts/                # 中间产物
├── pyproject.toml
└── CLAUDE.md
```

## 溯源与可观测性

每次分析生成唯一的 `trace_id`，所有数据按 trace 组织：

```
traces/{trace_id}/
├── timeline.json      # 时间线摘要（所有 Agent 步骤）
├── messages.json      # 消息总线完整日志
└── agents/
    ├── collector.json # Collector 执行步骤
    ├── analyst.json   # Analyst 执行步骤
    ├── writer.json    # Writer 执行步骤
    └── reviewer.json  # Reviewer 执行步骤

artifacts/{trace_id}/
├── 01_collector.json  # 采集结果
├── 02_analyst.json    # 分析结果
├── 04_writer.json     # 报告
└── 05_reviewer.json   # 质检结论
```

## 技术栈

| 组件 | 技术 |
|---|---|
| DAG 编排 | LangGraph |
| LLM 调用 | LangChain + langchain-openai |
| 搜索 | Tavily Search API |
| 数据模型 | Pydantic V2 |
| 前端 | Streamlit |
| 测试 | Pytest |
| 日志 | Loguru |

## License

MIT
