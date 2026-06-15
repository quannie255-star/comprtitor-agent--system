"""
Benchmark 评估脚本

将 Agent 输出与 Ground Truth 对比，计算准确率和召回率。
用法：
    python benchmarks/evaluate.py --product Notion
    python benchmarks/evaluate.py --all
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.orchestrator import Orchestrator


def load_ground_truth():
    path = os.path.join(os.path.dirname(__file__), "ground_truth.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def evaluate_profile(profile: dict, gt: dict) -> dict:
    """评估单个 Agent 输出 vs Ground Truth"""
    pname = profile.get("name", "")

    # 公司名准确率
    company_hit = gt["company"].lower() in profile.get("company", "").lower()

    # 分类准确率
    category_hit = gt["category"].lower() in profile.get("category", "").lower()

    # 定价模式
    pricing_hit = False
    pricing = profile.get("pricing") or {}
    if isinstance(pricing, dict):
        model = pricing.get("model", "").lower()
        gt_model = gt["pricing_model"].lower()
        pricing_hit = any(w in model for w in gt_model.split("/"))

    # 功能召回/精确率
    profile_features = {f.get("name", "") for f in profile.get("core_features", []) if isinstance(f, dict)}
    gt_features = set(gt["core_features"])

    feature_recall = len(profile_features & gt_features) / len(gt_features) if gt_features else 0
    feature_precision = len(profile_features & gt_features) / len(profile_features) if profile_features else 0

    # 优势/劣势召回
    profile_strengths = {s.get("content", "")[:20] for s in profile.get("strengths", []) if isinstance(s, dict)}
    gt_strengths = set(gt["strengths"])
    strength_recall = sum(1 for gs in gt_strengths if any(gs[:6] in ps for ps in profile_strengths)) / len(gt_strengths) if gt_strengths else 0

    profile_weaknesses = {w.get("content", "")[:20] for w in profile.get("weaknesses", []) if isinstance(w, dict)}
    gt_weaknesses = set(gt["weaknesses"])
    weakness_recall = sum(1 for gw in gt_weaknesses if any(gw[:6] in pw for pw in profile_weaknesses)) / len(gt_weaknesses) if gt_weaknesses else 0

    return {
        "product": pname,
        "company_accuracy": 1.0 if company_hit else 0.0,
        "category_accuracy": 1.0 if category_hit else 0.0,
        "pricing_accuracy": 1.0 if pricing_hit else 0.0,
        "feature_recall": round(feature_recall, 2),
        "feature_precision": round(feature_precision, 2),
        "strength_recall": round(strength_recall, 2),
        "weakness_recall": round(weakness_recall, 2),
    }


def run_evaluation(products: list[str], api_key: str = "") -> list[dict]:
    """对指定产品运行评估"""
    gt_data = load_ground_truth()
    results = []

    config = {
        "llm": {"provider": "openai", "model": "gpt-4o", "api_key": api_key},
        "search": {"api_key": os.getenv("TAVILY_API_KEY", "")},
        "agents": {"reviewer": {"max_review_rounds": 1}},
    }

    for product in products:
        gt = gt_data["products"].get(product)
        if not gt:
            print(f"⚠ {product} 不在 Ground Truth 中，跳过")
            continue

        print(f"🔍 评估 {product}...")
        orch = Orchestrator(config)
        result = orch.run(product, target_products=[product], use_langgraph=False)
        profiles = result.get("competitor_profiles", [])

        if profiles:
            scores = evaluate_profile(profiles[0], gt)
            results.append(scores)
        else:
            print(f"❌ {product}: 无 Profile 产出")

    return results


def print_summary(results: list[dict]):
    """打印评估摘要"""
    if not results:
        print("无评估结果")
        return

    print("\n" + "=" * 60)
    print("📊 Benchmark 评估结果")
    print("=" * 60)

    metrics = [
        "company_accuracy", "category_accuracy", "pricing_accuracy",
        "feature_recall", "feature_precision", "strength_recall", "weakness_recall",
    ]
    metric_names = {
        "company_accuracy": "公司识别",
        "category_accuracy": "分类识别",
        "pricing_accuracy": "定价识别",
        "feature_recall": "功能召回率",
        "feature_precision": "功能精确率",
        "strength_recall": "优势召回率",
        "weakness_recall": "劣势召回率",
    }

    for r in results:
        print(f"\n## {r['product']}")
        for m in metrics:
            bar = "█" * int(r[m] * 20) + "░" * (20 - int(r[m] * 20))
            print(f"  {metric_names[m]:<12} {bar} {r[m]:.0%}")

    avg = {m: sum(r[m] for r in results) / len(results) for m in metrics}
    print(f"\n{'─' * 40}")
    print("📈 平均值:")
    for m in metrics:
        print(f"  {metric_names[m]:<12} {avg[m]:.0%}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--product", type=str, help="评估单个产品")
    parser.add_argument("--all", action="store_true", help="评估所有 Ground Truth 产品")
    args = parser.parse_args()

    if args.product:
        products = [args.product]
    elif args.all:
        products = list(load_ground_truth()["products"].keys())
    else:
        print("用法: python benchmarks/evaluate.py --product Notion")
        print("      python benchmarks/evaluate.py --all")
        sys.exit(1)

    api_key = os.getenv("LLM_API_KEY", "")
    results = run_evaluation(products, api_key)
    print_summary(results)
