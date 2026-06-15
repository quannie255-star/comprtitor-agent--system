"""
Streamlit 前端 — Taste-Skill 设计风格

设计原则 (Taste-Skill):
  - VARIANCE: 非对称布局，输入/结果/溯源三区独立
  - DENSITY: 充足留白，卡片间距 >= 24px
  - TYPE: 清晰的 H1→H2→H3 层级递减
  - ANTI-GENERIC: 自定义灰调色板 + 克制的品牌蓝

启动方式：
    python -m streamlit run src/api/routes.py
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import streamlit as st
from dotenv import load_dotenv

from core.orchestrator import Orchestrator
from core.schema import AgentType, Priority

load_dotenv()

# ============================================================
# 页面配置
# ============================================================
st.set_page_config(
    page_title="竞品分析 · Agent 协作系统",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# 全局样式（MVP 级最小注入，仅 7 项精准改动）
# ============================================================
st.markdown("""
<style>
    /* 1. Inter 字体 + 层级（用系统原生字体栈，秒开无外部请求）*/
    html, body, [class*="css"], .stMarkdown, .stText, p, h1, h2, h3, h4 {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif;
    }
    h1 { font-weight: 700; font-size: 1.75rem; letter-spacing: -0.02em; }
    h2 { font-weight: 600; font-size: 1.25rem; letter-spacing: -0.01em; }
    h3 { font-weight: 600; font-size: 1.1rem; }
    p, li, td, th, .stMarkdown { font-weight: 400; line-height: 1.6; }

    /* 2. 色系变量 */
    :root {
        --primary: #165DFF;
        --primary-hover: #0E42D2;
        --primary-light: #E8F0FF;
        --slate-50: #F8FAFC;
        --slate-100: #F1F5F9;
        --slate-200: #E2E8F0;
        --slate-500: #64748B;
        --slate-700: #334155;
        --slate-900: #0F172A;
    }

    /* 3. 统一圆角 8px + 间距 */
    .stButton button, .stTextInput input, .stSelectbox [data-baseweb="select"],
    .stTextArea textarea, [data-testid="stExpander"] details,
    [data-testid="stMetricValue"], .stMultiSelect [data-baseweb="input"] {
        border-radius: 8px !important;
    }
    .stContainer, [data-testid="stVerticalBlock"] > div {
        gap: 8px;
    }

    /* 4. 输入框 & 按钮聚焦/悬停 */
    .stTextInput input, .stTextArea textarea {
        border: 1px solid var(--slate-200) !important;
        padding: 10px 14px !important;
        transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
    }
    .stTextInput input:focus, .stTextArea textarea:focus {
        border-color: var(--primary) !important;
        box-shadow: 0 0 0 3px rgba(22,93,255,0.12) !important;
    }
    .stButton > button {
        background: var(--primary) !important;
        color: #fff !important;
        border: none !important;
        padding: 10px 20px !important;
        font-weight: 500 !important;
        transition: background 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease !important;
    }
    .stButton > button:hover {
        background: var(--primary-hover) !important;
        box-shadow: 0 2px 8px rgba(22,93,255,0.25) !important;
        transform: translateY(-1px);
    }
    .stButton > button:active {
        transform: translateY(0);
    }
    [data-testid="stSidebar"] .stButton > button {
        background: #fff !important;
        color: var(--slate-700) !important;
        border: 1px solid var(--slate-200) !important;
    }
    [data-testid="stSidebar"] .stButton > button:hover {
        background: var(--slate-50) !important;
        border-color: var(--slate-500) !important;
        box-shadow: none !important;
    }

    /* 5. 侧边栏层次 */
    [data-testid="stSidebar"] {
        background: var(--slate-50) !important;
        border-right: 1px solid var(--slate-200) !important;
    }
    [data-testid="stSidebar"] .stMarkdown h3,
    [data-testid="stSidebar"] .stMarkdown p {
        color: var(--slate-700);
    }

    /* 6. 全局过渡 */
    * { transition: background 0.2s ease, border-color 0.2s ease, opacity 0.2s ease, color 0.2s ease; }

    /* 7. 卡片容器微调 */
    [data-testid="stExpander"] details {
        border: 1px solid var(--slate-200);
        background: #fff;
    }
    [data-testid="stExpander"] summary {
        font-weight: 500;
        color: var(--slate-700);
    }
</style>
""", unsafe_allow_html=True)

# ============================================================
# 自定义 CSS（最小化，仅用于 Taste-Skill 风格微调）
# ============================================================
st.markdown("""
<style>
    /* 全局字体微调 */
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif;
    }
    /* 卡片间距呼吸感 */
    .block-container { padding-top: 2rem; }
    /* 主内容区最大宽度 */
    .main .block-container { max-width: 1100px; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# 侧边栏 — Taste-Skill 极简风格
# ============================================================
with st.sidebar:
    st.markdown("### ◈ 竞品分析")
    st.caption("AI Agent 协作系统")
    st.divider()

    # LLM 配置 — 默认折叠
    with st.expander("模型配置", expanded=not bool(os.getenv("LLM_API_KEY"))):
        api_key = st.text_input(
            "API Key", value=os.getenv("LLM_API_KEY", ""),
            type="password", placeholder="sk-...", label_visibility="collapsed",
        )
        api_base = st.text_input(
            "API Base", value=os.getenv("LLM_API_BASE", ""),
            placeholder="留空使用默认", label_visibility="collapsed",
        )
        model = st.selectbox(
            "模型", ["gpt-4o", "gpt-4o-mini", "deepseek-v4-pro", "deepseek-chat"],
            index=0,
        )

    # 搜索配置
    with st.expander("搜索", expanded=False):
        tavily_key = st.text_input(
            "Tavily Key", value=os.getenv("TAVILY_API_KEY", ""),
            type="password", placeholder="tvly-...", label_visibility="collapsed",
        )

    # 分析维度
    with st.expander("分析维度", expanded=True):
        all_dims = ["核心功能", "定价策略", "用户体验", "技术架构", "市场定位", "安全合规", "集成生态"]
        selected_dims = []
        for dim in all_dims:
            if st.checkbox(dim, value=dim in ["核心功能", "定价策略", "用户体验", "市场定位"]):
                selected_dims.append(dim)

    st.divider()
    st.caption(f"已选 {len(selected_dims)} 个维度")

# ============================================================
# 主区域 — Tabs
# ============================================================
tab1, tab2 = st.tabs(["🔍 竞品分析", "🔎 Code Review"])

# ========================
# TAB 1: 竞品分析 (保留全部原有功能)
# ========================
with tab1:
    hero_l, hero_r = st.columns([3, 1])
    with hero_l:
        st.markdown("## 竞品分析 Agent 协作系统")
        st.caption("4 Agent · DAG 编排 · 全链路溯源 · 130 测试覆盖")
    with hero_r:
        st.markdown("")

    st.divider()

# ============================================================
# 输入区 — 非对称布局
# ============================================================
in_l, in_r = st.columns([3, 1])
with in_l:
    target = st.text_input(
        "竞品名称",
        placeholder="多竞品用逗号分隔，如 Notion, 飞书, Figma",
        label_visibility="collapsed",
        key="target_input",
    )
with in_r:
    targets_parsed = [t.strip() for t in target.replace("，", ",").split(",") if t.strip()][:3] if target else []
    hint_text = f"{len(targets_parsed)} 个竞品" if targets_parsed else "最多 3 个"
    st.caption(hint_text)
    run_btn = st.button("开始分析", type="primary", use_container_width=True, disabled=not targets_parsed)

st.markdown("<br>", unsafe_allow_html=True)  # 呼吸空间

# ============================================================
# 执行流水线
# ============================================================
if run_btn and targets_parsed:
    st.session_state.pop("last_result", None)
    st.session_state.pop("last_orchestrator", None)
    if "history" not in st.session_state:
        st.session_state.history = []

    config = {
        "llm": {"provider": "openai", "model": model, "api_key": api_key, "api_base": api_base, "temperature": 0.3},
        "search": {"api_key": tavily_key or os.getenv("TAVILY_API_KEY", "")},
        "agents": {"analyst": {"comparison_dimensions": selected_dims}, "reviewer": {"max_review_rounds": 3}},
        "orchestrator": {"recursion_limit": 25},
        "storage": {"traces_dir": "./traces", "outputs_dir": "./outputs", "artifacts_dir": "./artifacts"},
    }

    orchestrator = Orchestrator(config)

    with st.status("流水线执行中...", expanded=True) as pipeline_status:
        st.write("🔍 Collector — 搜索并采集竞品数据")
        st.write("📊 Analyst — 功能对比与 SWOT 分析")
        st.write("📝 Writer — 生成报告")
        st.write("✅ Reviewer — 质检审查")

    try:
        result = orchestrator.run(
            target_product=targets_parsed[0],
            target_products=targets_parsed,
            analysis_dimensions=selected_dims,
            use_langgraph=False,
        )
        pipeline_status.update(label="流水线执行完成", state="complete", expanded=False)
        st.session_state.last_result = result
        st.session_state.last_orchestrator = orchestrator
        st.session_state.history.append(", ".join(targets_parsed))
    except Exception as e:
        import traceback
        pipeline_status.update(label="执行失败", state="error")
        st.error(str(e))
        st.code(traceback.format_exc())
        st.stop()

    st.divider()

# ============================================================
# 报告展示区 — Editorial 风格
# ============================================================
if "last_result" in st.session_state and "last_orchestrator" in st.session_state:
    result = st.session_state.last_result
    orchestrator = st.session_state.last_orchestrator
    report_md = result.get("report", "")
    review_raw = result.get("review_result", {})
    review_score = review_raw.get("score", 0) if isinstance(review_raw, dict) else 0
    review_passed = review_raw.get("passed", False) if isinstance(review_raw, dict) else False

    # --- 工具栏（轻量）---
    tb1, tb2 = st.columns([4, 1])
    with tb1:
        st.markdown("### 竞品分析报告")
    with tb2:
        if report_md:
            product_name = targets_parsed[0] if targets_parsed else "竞品"
            fname = f"{product_name}_竞品分析报告.md" if len(targets_parsed) <= 1 else "多竞品对比_竞品分析报告.md"
            dl1, dl2 = st.columns(2)
            dl1.download_button("MD", data=report_md, file_name=fname, mime="text/markdown", use_container_width=True)
            from models.export import HTML_TEMPLATE, ReportExporter
            html_body = ReportExporter.markdown_to_html(report_md)
            html_full = HTML_TEMPLATE.format(title=fname.replace(".md", ""), body=html_body)
            dl2.download_button("HTML", data=html_full, file_name=fname.replace(".md", ".html"), mime="text/html", use_container_width=True)

    # --- 质检徽章 ---
    badge_text = "已通过质检" if review_passed else "待优化"
    badge_color = "#10B981" if review_passed else "#F59E0B"
    st.markdown(
        f'<span style="background:{badge_color}15;color:{badge_color};padding:4px 12px;'
        f'border-radius:20px;font-size:0.85em;font-weight:500">{badge_text} · {review_score:.0%}</span>',
        unsafe_allow_html=True,
    )
    st.markdown("<br>", unsafe_allow_html=True)

    # --- 功能对比矩阵（多竞品时）---
    feature_matrix = result.get("feature_matrix")
    if feature_matrix and isinstance(feature_matrix, dict):
        matrix_data = feature_matrix.get("matrix", {})
        competitors = feature_matrix.get("competitors", [])
        if matrix_data and len(competitors) > 1:
            with st.container(border=True):
                st.markdown("#### 功能对比矩阵")
                try:
                    import pandas as pd
                    df = pd.DataFrame(matrix_data).T
                    df.index.name = "维度"
                    st.dataframe(df, use_container_width=True)
                except ImportError:
                    st.info("安装 pandas 后可展示对比表格")
            st.divider()

    # --- 目录导航（侧边栏位置）---
    toc_entries = []
    for m in re.finditer(r'^(#{2,3})\s+(.+)$', report_md, re.MULTILINE):
        level = len(m.group(1))
        title = m.group(2).strip()
        anchor = re.sub(r'[^\w一-鿿]+', '-', title).strip('-').lower()
        toc_entries.append((anchor, title, level))

    if toc_entries:
        with st.expander("目录", expanded=False):
            cols = st.columns(min(3, max(1, len(toc_entries) // 6 + 1)))
            for i, (anchor, title, level) in enumerate(toc_entries):
                prefix = "  " if level == 3 else ""
                with cols[i % len(cols)]:
                    st.markdown(f"{prefix}- [{title}](#{anchor})")

    # --- 报告正文（Editorial 风格 + 溯源高亮）---
    if report_md:
        def add_anchor(match):
            hashes = match.group(1)
            title = match.group(2).strip()
            anchor = re.sub(r'[^\w一-鿿]+', '-', title).strip('-').lower()
            return f'<a name="{anchor}"></a>\n{hashes} {title}'

        anchored = re.sub(r'^(#{2,3})\s+(.+)$', add_anchor, report_md, flags=re.MULTILINE)
        highlighted = re.sub(
            r'\[(src_\w+)\]',
            r'<code style="background:#EFF6FF;color:#3B82F6;padding:1px 5px;border-radius:3px;font-size:0.85em">🔗 \1</code>',
            anchored,
        )
        st.markdown(highlighted, unsafe_allow_html=True)
    else:
        st.warning("报告内容为空，请检查 LLM 配置")

    st.divider()

    # --- 可观测性面板 ---
    st.markdown("### LLM 可观测性")

    obs1, obs2, obs3 = st.tabs(["调用链", "费用", "护栏"])

    tracer = getattr(orchestrator, "tracer", None)
    cost_tracker = getattr(orchestrator, "cost_tracker", None)
    guard = getattr(orchestrator, "guardrails", None)

    with obs1:
        if tracer:
            for span in tracer.spans:
                s = "✓" if span.success else "✗"
                st.text(f"{s} {span.agent_name} · {span.model} · {span.latency_ms:.0f}ms · in:{span.input_tokens} out:{span.output_tokens}")
        else:
            st.caption("无 LLM 调用记录")

    with obs2:
        if cost_tracker:
            cs = cost_tracker.summary()
            c1, c2, c3 = st.columns(3)
            c1.metric("总费用", f"${cs.get('total_cost', 0):.4f}")
            c2.metric("单次均价", f"${cs.get('avg_cost_per_call', 0):.6f}")
            c3.metric("vs GPT-4o 节省", cs.get("vs_gpt4o_savings_pct", "N/A"))
        else:
            st.caption("无费用记录")

    with obs3:
        if guard:
            gs = guard.summary()
            st.metric("拦截 / 告警", f"{gs['blocked']} / {gs['warnings']}")

    # --- 溯源摘要 ---
    st.divider()
    st.caption(
        f"Trace `{orchestrator.trace_id[:16]}...` · "
        f"轨迹 `traces/{orchestrator.trace_id}/` · "
        f"审计 `audits/{orchestrator.trace_id}/`"
    )

# ========================
# TAB 2: Code Review (Product Line 2)
# ========================
with tab2:
    st.markdown("## Code Review · Multi-Agent 审查")
    st.caption("Claude Code 架构审查 + Codex CLI 实现审查 · 质量门禁 · DORA 指标")
    st.divider()

    cr_left, cr_right = st.columns([2, 1])
    with cr_left:
        pr_title = st.text_input("PR 标题", placeholder="如: Fix JWT token refresh bug", key="pr_title")
        pr_desc = st.text_area("PR 描述", placeholder="简要描述变更内容...", height=80, key="pr_desc")
        pr_author = st.text_input("Author", value="dev", key="pr_author")

    with cr_right:
        agent_choice = st.selectbox("审查 Agent", ["auto (智能路由)", "claude", "codex", "all"], index=0)
        changed_files_text = st.text_area(
            "变更文件 (每行一个)", placeholder="src/auth.py\nsrc/middleware.py\ntests/test_auth.py",
            height=100, key="changed_files",
        )
        additions = st.number_input("总新增行数", min_value=0, value=50, key="additions")
        deletions = st.number_input("总删除行数", min_value=0, value=10, key="deletions")

    review_btn = st.button("开始审查", type="primary", use_container_width=True,
                           disabled=not bool(pr_title.strip()))

    if review_btn:
        # 构建 PR data
        files_raw = [f.strip() for f in changed_files_text.split("\n") if f.strip()]
        changed_files = [
            {"path": f, "additions": max(1, additions // max(len(files_raw), 1)),
             "deletions": max(0, deletions // max(len(files_raw), 1)),
             "diff": f"(mock diff for {f})"}
            for f in (files_raw or ["src/main.py"])
        ]

        pr_data = {
            "title": pr_title.strip(),
            "description": pr_desc.strip(),
            "author": pr_author.strip(),
            "changed_files": changed_files,
            "total_additions": additions,
            "total_deletions": deletions,
        }

        # Agent 选择
        selected = None
        if agent_choice != "auto (智能路由)":
            selected = [agent_choice] if agent_choice != "all" else ["claude", "codex"]

        config = {
            "llm": {"provider": "openai", "model": model, "api_key": api_key, "api_base": api_base},
            "storage": {"traces_dir": "./traces", "outputs_dir": "./outputs", "artifacts_dir": "./artifacts"},
        }
        orchestrator = Orchestrator(config)

        with st.status("审查流水线执行中...", expanded=True) as cr_status:
            st.write("📥 Collector — 采集 PR 变更数据")
            st.write("🔍 Analyst — 双轨并行审查 (Claude + Codex)")
            st.write("📝 Writer — 生成审查报告")
            st.write("🚦 Reviewer — 质量门禁判定")

        try:
            cr_result = orchestrator.review_pr(pr_data, selected_agents=selected)
            cr_status.update(label="审查完成", state="complete", expanded=False)
            st.session_state.cr_result = cr_result
        except Exception as e:
            import traceback
            cr_status.update(label="审查失败", state="error")
            st.error(str(e))
            st.code(traceback.format_exc())
            st.stop()

    # --- 审查结果展示 ---
    if "cr_result" in st.session_state:
        cr = st.session_state.cr_result
        report = cr.get("report", "")
        review_result = cr.get("review_result", {})
        dora = cr.get("dora_metrics", {})
        agenthub = cr.get("agenthub_metrics", {})
        score_data = cr.get("review_score", {})

        if report:
            st.divider()

            # 分数仪表盘
            st.markdown("### Review Score")
            if score_data:
                cols = st.columns(6)
                metrics_list = [
                    ("Overall", score_data.get("overall", 0)),
                    ("Architecture", score_data.get("architecture", 0)),
                    ("Security", score_data.get("security", 0)),
                    ("Performance", score_data.get("performance", 0)),
                    ("Test Cov.", score_data.get("test_coverage", 0)),
                    ("Maint.", score_data.get("maintainability", 0)),
                ]
                for i, (label, val) in enumerate(metrics_list):
                    color = "#10B981" if val >= 8 else "#F59E0B" if val >= 6 else "#EF4444"
                    cols[i].metric(label, f"{val:.1f}/10")

            # 质量门禁
            passed = review_result.get("passed", False) if isinstance(review_result, dict) else False
            badge = "✅ PASSED" if passed else "❌ FAILED"
            badge_c = "#10B981" if passed else "#EF4444"
            st.markdown(
                f'<span style="background:{badge_c}15;color:{badge_c};padding:4px 12px;'
                f'border-radius:20px;font-size:0.9em;font-weight:600">Quality Gate: {badge}</span>',
                unsafe_allow_html=True,
            )
            st.markdown("<br>", unsafe_allow_html=True)

            # DORA 指标
            if dora:
                st.markdown("#### DORA Metrics")
                dc = st.columns(4)
                dc[0].metric("Deploy Freq", f"{dora.get('deployment_frequency', 0):.1f}/wk")
                dc[1].metric("Lead Time", f"{dora.get('lead_time_hours', 0):.1f}h")
                dc[2].metric("Failure Rate", f"{dora.get('change_failure_rate', 0):.1f}%")
                dc[3].metric("MTTR", f"{dora.get('mttr_hours', 0):.1f}h")
                level = dora.get("performance_level", "N/A") if isinstance(dora, dict) else "N/A"
                st.caption(f"Performance Level: **{level.upper() if isinstance(level, str) else level}**")

            # AgentHub 指标
            if agenthub:
                with st.expander("AgentHub Metrics", expanded=False):
                    ac = st.columns(4)
                    ac[0].metric("AI Coverage", f"{agenthub.get('ai_review_coverage', 0):.1%}")
                    ac[1].metric("Detection Rate", f"{agenthub.get('ai_issue_detection_rate', 0):.1%}")
                    ac[2].metric("Fix Adoption", f"{agenthub.get('ai_fix_adoption_rate', 0):.1%}")
                    ac[3].metric("Time Saved", f"{agenthub.get('human_review_time_saved_pct', 0):.1%}")
                    bc = st.columns(3)
                    bc[0].metric("Multi-Agent Gain", f"{agenthub.get('multi_agent_efficiency_gain', 0):.1%}")
                    bc[1].metric("Util. Balance", f"{agenthub.get('agent_utilization_balance', 0):.1%}")
                    bc[2].metric("Cost/Review", f"${agenthub.get('cost_per_review_usd', 0):.2f}")

            # 报告正文
            st.markdown("---")
            st.markdown(report, unsafe_allow_html=True)

            # 下载
            dl1, dl2 = st.columns(2)
            dl1.download_button("Download MD", data=report, file_name=f"review_{pr_title.strip()[:30]}.md", mime="text/markdown")
            dl2.download_button("Download JSON", data=str(cr), file_name=f"review_{pr_title.strip()[:30]}.json", mime="application/json")
