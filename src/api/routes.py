"""
Streamlit 前端 — 竞品分析 Agent 协作系统

卡片化布局 + 目录导航 + 溯源高亮 + 质检评分 + 一键下载。

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

load_dotenv()

# ============================================================
# 页面配置
# ============================================================
st.set_page_config(
    page_title="竞品分析 Agent 协作系统",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# 侧边栏
# ============================================================
with st.sidebar:
    st.markdown("## 🔍 竞品分析")
    st.caption("AI Agent 协作系统 v0.1")
    st.divider()

    with st.expander("⚡ LLM 配置", expanded=not os.getenv("LLM_API_KEY")):
        api_key = st.text_input(
            "API Key", value=os.getenv("LLM_API_KEY", ""),
            type="password", placeholder="sk-...", key="llm_key",
        )
        api_base = st.text_input(
            "API Base（可选）", value=os.getenv("LLM_API_BASE", ""),
            placeholder="https://api.deepseek.com/v1", key="llm_base",
        )
        is_deepseek = "deepseek" in (api_base or "").lower()
        model_list = (
            ["deepseek-v4-pro", "deepseek-v4-flash"]
            if is_deepseek
            else ["gpt-4o", "gpt-4o-mini", "deepseek-v4-pro", "claude-sonnet-4-6"]
        )
        default_idx = 0 if is_deepseek else 0
        model = st.selectbox(
            "模型", model_list, index=default_idx, key="model",
        )

    with st.expander("🔎 搜索配置", expanded=False):
        tavily_key = st.text_input(
            "Tavily API Key", value=os.getenv("TAVILY_API_KEY", ""),
            type="password", placeholder="tvly-...", key="tavily_key",
        )
        st.caption("留空使用 mock 数据")

    with st.expander("📊 分析维度", expanded=True):
        all_dims = ["核心功能", "定价策略", "用户体验", "技术架构", "市场定位", "安全合规", "集成生态"]
        selected_dims = []
        for dim in all_dims:
            if st.checkbox(dim, value=dim in ["核心功能", "定价策略", "用户体验", "市场定位"]):
                selected_dims.append(dim)

    st.divider()
    st.caption(f"选中 {len(selected_dims)} 个维度")

# ============================================================
# 主区域 Header
# ============================================================
st.markdown("### 🤖 AI 驱动的竞品分析系统")
st.caption("4 Agent 协作 · DAG 编排 · 全链路溯源 · 128 测试覆盖")

# ============================================================
# 输入卡片
# ============================================================
input_card = st.container(border=True)
with input_card:
    col1, col2 = st.columns([4, 1])
    with col1:
        target = st.text_input(
            "🎯 竞品名称", placeholder="多竞品用逗号分隔，如：Notion, Confluence, 飞书",
            label_visibility="collapsed", key="target",
        )
    with col2:
        targets_parsed = [t.strip() for t in target.replace("，", ",").split(",") if t.strip()][:3] if target else []
        # 过滤单字符（防止字符串迭代陷阱的残留污染）
        targets_parsed = [t for t in targets_parsed if len(t) >= 2]
        hint = f"{len(targets_parsed)} 个竞品" if targets_parsed else ""
        st.caption(hint)
        run_btn = st.button("🚀 开始分析", type="primary", use_container_width=True, disabled=not targets_parsed)

# ============================================================
# 执行流水线
# ============================================================
if run_btn and targets_parsed:
    # 清理上一次分析的状态，防止跨运行污染
    st.session_state.pop("last_result", None)
    st.session_state.pop("last_orchestrator", None)
    if "history" not in st.session_state:
        st.session_state.history = []

    config = {
        "llm": {"provider": "openai", "model": model, "api_key": api_key, "api_base": api_base, "temperature": 0.3},
        "search": {"api_key": tavily_key},
        "agents": {"analyst": {"comparison_dimensions": selected_dims}, "reviewer": {"max_review_rounds": 3}},
        "orchestrator": {"recursion_limit": 25},
        "storage": {"traces_dir": "./traces", "outputs_dir": "./outputs", "artifacts_dir": "./artifacts"},
    }

    orchestrator = Orchestrator(config)

    # --- 步骤日志 ---
    pipeline_card = st.container(border=True)
    with pipeline_card:
        st.markdown("#### 📡 执行流水线")

        with st.status("🔍 **Collector** — 搜索并采集竞品数据", expanded=True) as p1:
            st.write("搜索目标产品...")
            st.write("抓取网页内容...")
            st.write("LLM 结构化解析...")

        with st.status("📊 **Analyst** — 功能对比与 SWOT 分析", expanded=True) as p2:
            st.write("构建功能对比矩阵...")
            st.write("生成 SWOT 分析...")
            st.write("提炼市场洞察...")

        with st.status("📝 **Writer** — 生成竞品报告", expanded=True) as p3:
            st.write("撰写执行摘要...")
            st.write("拼装报告章节...")
            st.write("渲染 Markdown...")

        with st.status("✅ **Reviewer** — 交叉审查与质检", expanded=True) as p4:
            st.write("编程化基础检查...")
            st.write("LLM 深度审查...")
            st.write("生成质检结论...")

    try:
        result = orchestrator.run(
            target_product=targets_parsed[0], analysis_dimensions=selected_dims,
            use_langgraph=False, target_products=targets_parsed,
        )
        p1.update(label="🔍 **Collector** — 采集完成", state="complete", expanded=False)
        p2.update(label="📊 **Analyst** — 分析完成", state="complete", expanded=False)
        p3.update(label="📝 **Writer** — 报告生成完成", state="complete", expanded=False)

        review_raw = result.get("review_result", {})
        passed = review_raw.get("passed", False) if isinstance(review_raw, dict) else False
        if passed:
            p4.update(label="✅ **Reviewer** — 质检通过", state="complete", expanded=False)
        else:
            p4.update(label="⚠️ **Reviewer** — 质检完成（存在建议）", state="complete", expanded=False)

        st.session_state.last_result = result
        st.session_state.last_orchestrator = orchestrator
        st.session_state.history.append(target)

    except Exception as e:
        import traceback
        p1.update(label="❌ 执行失败", state="error")
        st.error(f"流水线执行出错: {e}")
        st.code(traceback.format_exc())
        st.stop()

    st.divider()

# ============================================================
# 报告展示区
# ============================================================
if "last_result" in st.session_state and "last_orchestrator" in st.session_state:
    result = st.session_state.last_result
    orchestrator = st.session_state.last_orchestrator
    report_md = result.get("report", "")
    review_raw = result.get("review_result", {})
    review_score = review_raw.get("score", 0) if isinstance(review_raw, dict) else 0
    review_passed = review_raw.get("passed", False) if isinstance(review_raw, dict) else False

    # --- 工具栏行 ---
    tool1, tool2, tool3, tool4 = st.columns([3, 1, 1, 1])
    with tool1:
        st.markdown("### 📄 竞品分析报告")
    with tool2:
        if review_passed:
            st.success(f"🟢 质检通过 ({review_score:.0%})")
        else:
            st.warning(f"🟡 待优化 ({review_score:.0%})")
    with tool3:
        if report_md:
            product_name = (targets_parsed or ["竞品"])[0] if "targets_parsed" in dir() else "竞品"
            fname = f"{product_name}_竞品分析报告.md" if len(targets_parsed or []) <= 1 else f"多竞品对比_竞品分析报告.md"
            st.download_button(
                "📥 下载 MD", data=report_md, file_name=fname,
                mime="text/markdown", use_container_width=True,
            )
    with tool4:
        if report_md:
            from models.export import ReportExporter
            html_content = ReportExporter.markdown_to_html(report_md)
            html_full = ReportExporter.HTML_TEMPLATE.format(
                title=fname.replace(".md", ""),
                body=html_content,
            )
            st.download_button(
                "📄 下载 HTML", data=html_full, file_name=fname.replace(".md", ".html"),
                mime="text/html", use_container_width=True,
            )

    # --- 目录导航 ---
    toc_entries: list[tuple[str, str, int]] = []  # (anchor, title, level)
    for m in re.finditer(r'^(#{2,3})\s+(.+)$', report_md, re.MULTILINE):
        level = len(m.group(1))
        title = m.group(2).strip()
        anchor = re.sub(r'[^\w一-鿿]+', '-', title).strip('-').lower()
        toc_entries.append((anchor, title, level))

    if toc_entries:
        toc_card = st.container(border=True)
        with toc_card:
            toc_tab = st.expander("📑 目录导航", expanded=False)
            with toc_tab:
                cols = st.columns(min(3, max(1, len(toc_entries) // 6 + 1)))
                for i, (anchor, title, level) in enumerate(toc_entries):
                    prefix = "  " if level == 3 else ""
                    with cols[i % len(cols)]:
                        st.markdown(f"{prefix}- [{title}](#{anchor})")

    # --- 功能对比矩阵可视化（多竞品时显示）---
    feature_matrix = result.get("feature_matrix")
    if feature_matrix and isinstance(feature_matrix, dict):
        matrix_data = feature_matrix.get("matrix", {})
        competitors = feature_matrix.get("competitors", [])
        if matrix_data and len(competitors) > 1:
            matrix_card = st.container(border=True)
            with matrix_card:
                st.subheader("📊 功能对比矩阵")
                try:
                    import pandas as pd
                    df = pd.DataFrame(matrix_data).T
                    df.index.name = "维度"
                    st.dataframe(df, use_container_width=True)
                except ImportError:
                    st.info("安装 pandas 后可展示交互式对比表格: `pip install pandas`")
            st.divider()

    # --- 报告正文 ---
    report_card = st.container(border=True)
    with report_card:
        if report_md:
            # 为每个 ## 和 ### 标题插入 HTML anchor
            def add_anchor(match):
                hashes = match.group(1)
                title = match.group(2).strip()
                anchor = re.sub(r'[^\w一-鿿]+', '-', title).strip('-').lower()
                return f'<a name="{anchor}"></a>\n{hashes} {title}'

            anchored_md = re.sub(r'^(#{2,3})\s+(.+)$', add_anchor, report_md, flags=re.MULTILINE)

            # 溯源高亮：把 [src_xxx] 替换为蓝色标签
            highlighted = re.sub(
                r'\[(src_\w+)\]',
                r'<span style="background:#E8F0FE;color:#1E6FE9;padding:1px 6px;border-radius:4px;font-size:0.85em;font-family:monospace">🔗 \1</span>',
                anchored_md,
            )
            st.markdown(highlighted, unsafe_allow_html=True)
        else:
            st.warning("报告内容为空，请检查 LLM 配置")

    # --- 底部溯源卡片 ---
    st.divider()
    summary = orchestrator.get_summary()

    trace_card = st.container(border=True)
    with trace_card:
        st.markdown("#### 🔗 执行溯源")

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Collector", f"{summary['collector_steps']} 步")
        c2.metric("Analyst", f"{summary['analyst_steps']} 步")
        c3.metric("Writer", f"{summary['writer_steps']} 步")
        c4.metric("Reviewer", f"{summary['reviewer_steps']} 步")
        c5.metric("消息数", summary["messages"])
        c6.metric("Trace ID", orchestrator.trace_id[:8] + "...")

        with st.expander("📨 消息时间线"):
            for msg in orchestrator.bus.get_message_log():
                icons = {"data_output": "📤", "review_feedback": "🔄", "task_complete": "✅", "task_start": "🚀", "task_failed": "❌"}
                icon = icons.get(msg.msg_type.value, "📌")
                st.text(f"{icon} [{msg.timestamp.strftime('%H:%M:%S')}] {msg.sender} → {msg.receiver or 'ALL'} | {msg.msg_type.value}")

        st.caption(f"轨迹: `traces/{orchestrator.trace_id}/` | 产物: `artifacts/{orchestrator.trace_id}/`")
