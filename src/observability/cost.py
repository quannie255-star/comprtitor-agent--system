"""
LLM 成本追踪器

按模型定价实时计算每次 LLM 调用的费用。
支持多模型价格对比，输出到 CSV / JSON。

价格基准（2026 Q2，单位：美元/1M tokens）：
  来源：各厂商官网公开定价
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# ============================================================
# 模型价格表（输入/输出 每 1M tokens）
# ============================================================

MODEL_PRICING = {
    # OpenAI
    "gpt-4o":           {"input": 2.50,  "output": 10.00, "provider": "OpenAI"},
    "gpt-4o-mini":      {"input": 0.15,  "output": 0.60,  "provider": "OpenAI"},
    "gpt-4-turbo":      {"input": 10.00, "output": 30.00, "provider": "OpenAI"},
    # Anthropic
    "claude-sonnet-4-6": {"input": 3.00,  "output": 15.00, "provider": "Anthropic"},
    "claude-opus-4-8":   {"input": 15.00, "output": 75.00, "provider": "Anthropic"},
    # DeepSeek
    "deepseek-v4-pro":   {"input": 0.55,  "output": 2.19,  "provider": "DeepSeek"},
    "deepseek-v4-flash": {"input": 0.14,  "output": 0.55,  "provider": "DeepSeek"},
    "deepseek-chat":     {"input": 0.14,  "output": 0.28,  "provider": "DeepSeek"},
    # 默认
    "unknown":          {"input": 1.00,   "output": 4.00,  "provider": "Unknown"},
}


@dataclass
class CostRecord:
    """单次 LLM 调用的费用记录"""
    timestamp: str
    call_id: str
    agent_name: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: float
    input_cost: float      # $
    output_cost: float     # $
    total_cost: float      # $

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "call_id": self.call_id,
            "agent": self.agent_name,
            "model": self.model,
            "provider": self.provider,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "input_cost": f"${self.input_cost:.6f}",
            "output_cost": f"${self.output_cost:.6f}",
            "total_cost": f"${self.total_cost:.6f}",
        }


class CostTracker:
    """LLM 成本追踪器

    从 LLMTracer 的 spans 计算每次调用的费用，
    聚合按 Agent / Model / Provider 维度统计。

    使用方式：
        tracker = CostTracker()
        for span in tracer.spans:
            tracker.record(span)
        tracker.summary()  # → {"total_cost": 0.023, "by_agent": {...}}
    """

    def __init__(self):
        self.records: list[CostRecord] = []

    @staticmethod
    def get_price(model: str, token_type: str = "input") -> float:
        """查询模型单价 ($/1M tokens)"""
        pricing = MODEL_PRICING.get(model, MODEL_PRICING["unknown"])
        return pricing.get(token_type, 1.0)

    @staticmethod
    def calc_cost(model: str, input_tokens: int, output_tokens: int) -> tuple[float, float, float]:
        """计算单次调用费用"""
        input_price = CostTracker.get_price(model, "input")
        output_price = CostTracker.get_price(model, "output")
        input_cost = (input_tokens / 1_000_000) * input_price
        output_cost = (output_tokens / 1_000_000) * output_price
        return input_cost, output_cost, input_cost + output_cost

    def record(self, span) -> CostRecord:
        """从 tracer span 记录一条费用"""
        input_cost, output_cost, total_cost = self.calc_cost(
            span.model, span.input_tokens, span.output_tokens
        )
        record = CostRecord(
            timestamp=span.started_at.isoformat() if span.started_at else datetime.now().isoformat(),
            call_id=span.call_id,
            agent_name=span.agent_name,
            model=span.model,
            provider=MODEL_PRICING.get(span.model, MODEL_PRICING["unknown"])["provider"],
            input_tokens=span.input_tokens,
            output_tokens=span.output_tokens,
            total_tokens=span.input_tokens + span.output_tokens,
            latency_ms=span.latency_ms,
            input_cost=input_cost,
            output_cost=output_cost,
            total_cost=total_cost,
        )
        self.records.append(record)
        return record

    def summary(self) -> dict:
        """费用摘要：总成本 + 按 Agent/Model 拆分"""
        if not self.records:
            return {"total_cost": 0, "total_tokens": 0, "total_calls": 0}

        total_cost = sum(r.total_cost for r in self.records)
        total_tokens = sum(r.total_tokens for r in self.records)

        # 按 Agent 聚合
        by_agent = {}
        for r in self.records:
            if r.agent_name not in by_agent:
                by_agent[r.agent_name] = {"cost": 0.0, "tokens": 0, "calls": 0}
            by_agent[r.agent_name]["cost"] += r.total_cost
            by_agent[r.agent_name]["tokens"] += r.total_tokens
            by_agent[r.agent_name]["calls"] += 1

        # 按 Model 聚合
        by_model = {}
        for r in self.records:
            key = f"{r.provider}/{r.model}"
            if key not in by_model:
                by_model[key] = {"cost": 0.0, "tokens": 0, "calls": 0}
            by_model[key]["cost"] += r.total_cost
            by_model[key]["tokens"] += r.total_tokens
            by_model[key]["calls"] += 1

        # 节省估算（用 GPT-4o 作为对比基准）
        gpt4o_cost = sum(
            sum(c) for c in [self.calc_cost("gpt-4o", r.input_tokens, r.output_tokens)
            for r in self.records]
        )
        savings = gpt4o_cost - total_cost

        return {
            "total_cost": round(total_cost, 6),
            "total_tokens": total_tokens,
            "total_calls": len(self.records),
            "avg_cost_per_call": round(total_cost / len(self.records), 6),
            "by_agent": {k: {"cost": round(v["cost"], 6), "tokens": v["tokens"], "calls": v["calls"]}
                         for k, v in by_agent.items()},
            "by_model": {k: {"cost": round(v["cost"], 6), "tokens": v["tokens"], "calls": v["calls"]}
                         for k, v in by_model.items()},
            "vs_gpt4o_savings": round(savings, 6),
            "vs_gpt4o_savings_pct": f"{round(savings / gpt4o_cost * 100, 1)}%" if gpt4o_cost > 0 else "N/A",
        }

    def to_csv(self, filepath: str = "./cost_report.csv") -> str:
        """导出 CSV 报告"""
        if not self.records:
            return ""
        import csv
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "timestamp", "call_id", "agent", "model", "provider",
                "input_tokens", "output_tokens", "total_tokens",
                "latency_ms", "input_cost", "output_cost", "total_cost",
            ])
            writer.writeheader()
            for r in self.records:
                writer.writerow(r.to_dict())
        return filepath
