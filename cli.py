#!/usr/bin/env python3
"""
竞品分析 CLI 工具

用法：
    python cli.py run "Notion"                        # 单竞品分析
    python cli.py run "Notion,飞书"                    # 多竞品对比
    python cli.py run "Notion" --dimensions 功能,定价   # 自定义维度
    python cli.py trace <trace_id>                     # 查看执行轨迹
    python cli.py trace list                           # 列出所有轨迹
    python cli.py cost <trace_id>                      # 查看费用明细
    python cli.py prompts                              # 查看所有 Prompt
    python cli.py prompts analyst_comparison            # 查看单个 Prompt
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from dotenv import load_dotenv
load_dotenv()


def cmd_run(args):
    """执行竞品分析"""
    from core.orchestrator import Orchestrator

    targets = [t.strip() for t in args.target.replace("，", ",").split(",") if t.strip()][:3]
    dims = [d.strip() for d in args.dimensions.split(",")] if args.dimensions else None

    config = {
        "llm": {
            "provider": "openai",
            "model": args.model,
            "api_key": os.getenv("LLM_API_KEY", ""),
            "api_base": os.getenv("LLM_API_BASE", ""),
        },
        "search": {"api_key": os.getenv("TAVILY_API_KEY", "")},
        "agents": {"reviewer": {"max_review_rounds": args.max_rounds}},
        "storage": {"outputs_dir": args.output, "traces_dir": "./traces", "artifacts_dir": "./artifacts"},
    }

    print(f"🔍 分析目标: {', '.join(targets)}")
    print(f"📊 维度: {dims or '默认'}")
    print(f"🤖 模型: {args.model}")
    print()

    orch = Orchestrator(config)
    result = orch.run(targets[0], target_products=targets, analysis_dimensions=dims, use_langgraph=False)

    report = result.get("report", "")
    review = result.get("review_result", {})

    # 保存报告
    os.makedirs(args.output, exist_ok=True)
    fname = f"{targets[0]}_竞品分析报告.md"
    filepath = os.path.join(args.output, fname)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)

    # 摘要
    summary = orch.get_summary()
    print(f"✅ 报告已保存: {filepath}")
    print(f"📄 报告长度: {len(report)} 字符")
    print(f"📊 竞品画像: {len(result.get('competitor_profiles', []))} 个")
    print(f"🔗 Trace ID: {orch.trace_id}")
    print(f"💵 LLM 费用: ${summary.get('llm_cost', 0):.4f}")
    print(f"📡 LLM 调用: {summary.get('llm_calls', 0)} 次, {summary.get('llm_tokens', 0):,} tokens")
    if isinstance(review, dict):
        status = "✅ 通过" if review.get("passed") else "❌ 未通过"
        print(f"✅ 质检: {status} ({review.get('score', 0):.0%})")


def cmd_trace(args):
    """查看执行轨迹"""
    from storage.trace_store import TraceStore

    store = TraceStore(base_dir="./traces")

    if args.trace_id == "list":
        import glob
        traces = glob.glob("traces/*/timeline.json")
        if not traces:
            print("(无轨迹记录)")
            return
        print(f"共 {len(traces)} 条轨迹:\n")
        for t in sorted(traces, reverse=True)[:20]:
            tid = t.split(os.sep)[-2]
            with open(t, encoding="utf-8") as f:
                tl = json.load(f)
            print(f"  {tid[:16]}... | {tl['event_count']} events | {tl['generated_at'][:19]}")
        return

    data = store.load_trace(args.trace_id)
    if not data:
        print(f"❌ 轨迹 {args.trace_id} 不存在")
        return

    print(f"=== 轨迹 {args.trace_id} ===\n")
    tl = data.get("timeline", {})
    print(f"事件数: {tl.get('event_count', 0)}")
    print(f"消息数: {tl.get('message_count', 0)}")
    print()

    for event in tl.get("events", []):
        print(f"  [{event.get('time', '')[:19]}] {event.get('agent', '')}: {event.get('action', '')} — {event.get('summary', '')}")


def cmd_cost(args):
    """查看费用明细"""
    import glob

    if args.trace_id:
        traces = [f"traces/{args.trace_id}"]
    else:
        traces = sorted(glob.glob("traces/*/"))
        if not traces:
            print("(无轨迹记录)")
            return

    total_cost = 0
    for t in traces[-10:]:  # 最近 10 条
        tid = t.split(os.sep)[-2] if t.endswith(os.sep) else t.split(os.sep)[-1]
        audit_file = f"audits/{tid}/summary.json"
        if os.path.exists(audit_file):
            with open(audit_file) as f:
                s = json.load(f)
            print(f"  {tid[:16]} | llm_calls={s.get('total_llm_calls',0)} | events={s.get('total_events',0)}")


def cmd_prompts(args):
    """查看 Prompt 模板"""
    import glob
    import yaml

    prompts_dir = os.path.join(os.path.dirname(__file__), "prompts")

    if args.name:
        path = os.path.join(prompts_dir, f"{args.name}.yaml")
        if not os.path.exists(path):
            print(f"❌ Prompt '{args.name}' 不存在")
            print(f"可用: {[os.path.splitext(os.path.basename(p))[0] for p in glob.glob(prompts_dir + '/*.yaml')]}")
            return
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        print(f"=== {args.name} ===\n")
        if data.get("system"):
            print(f"[System]\n{data['system']}\n")
        if data.get("prompt"):
            print(f"[Prompt]\n{data['prompt']}")
        return

    # 列出所有
    files = sorted(glob.glob(prompts_dir + "/*.yaml"))
    print(f"共 {len(files)} 个 Prompt 模板:\n")
    for fp in files:
        name = os.path.splitext(os.path.basename(fp))[0]
        with open(fp, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        desc = data.get("system", "").strip()[:60]
        print(f"  {name:<30} {desc}")


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="竞品分析 Agent 协作系统 CLI")
    sub = parser.add_subparsers(dest="command")

    # run
    p_run = sub.add_parser("run", help="执行竞品分析")
    p_run.add_argument("target", help="竞品名称，多竞品用逗号分隔")
    p_run.add_argument("--dimensions", "-d", help="分析维度，逗号分隔")
    p_run.add_argument("--model", "-m", default="gpt-4o", help="LLM 模型")
    p_run.add_argument("--output", "-o", default="./outputs", help="输出目录")
    p_run.add_argument("--max-rounds", type=int, default=3, help="质检最大轮次")

    # trace
    p_trace = sub.add_parser("trace", help="查看执行轨迹")
    p_trace.add_argument("trace_id", nargs="?", default="list", help="Trace ID 或 'list'")

    # cost
    p_cost = sub.add_parser("cost", help="查看费用")
    p_cost.add_argument("trace_id", nargs="?", default="", help="Trace ID（可选）")

    # prompts
    p_prompts = sub.add_parser("prompts", help="查看 Prompt 模板")
    p_prompts.add_argument("name", nargs="?", default="", help="Prompt 名称")

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "trace":
        cmd_trace(args)
    elif args.command == "cost":
        cmd_cost(args)
    elif args.command == "prompts":
        cmd_prompts(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
