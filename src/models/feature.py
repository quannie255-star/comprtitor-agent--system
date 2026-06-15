"""
功能对比分析模型

基于采集的 CompetitorProfile 数据，构建功能对比矩阵。
包含分析 Prompt 模板和维度提取工具。
"""

from loguru import logger

from core.schema import CompetitorProfile, Evidence, FeatureMatrix

# ============================================================
# 分析维度定义
# ============================================================

DEFAULT_DIMENSIONS = [
    "核心功能完整性",
    "协作能力",
    "集成生态",
    "移动端体验",
    "定价灵活性",
    "技术架构先进性",
    "用户体验",
    "安全合规",
]

# ============================================================
# 分析 Prompt 模板
# ============================================================

FEATURE_COMPARISON_PROMPT = """你是一位资深的产品分析师。请基于以下竞品信息，生成功能对比分析。

## 竞品信息
{competitor_data}

## 对比维度
{dimensions}

## 输出要求
请以 JSON 格式输出功能对比矩阵（只输出 JSON）：

```json
{{
  "matrix": {{
    "维度1": {{"竞品A": "评价", "竞品B": "评价"}},
    "维度2": {{"竞品A": "评价", "竞品B": "评价"}}
  }},
  "summary": "2-3句话的对比总结，指出关键差异",
  "key_findings": [
    "发现1：具体的对比发现",
    "发现2：具体的对比发现"
  ]
}}
```

## 规则
1. 评价用简洁的短语（5-15字）
2. 无法对比的维度填"数据不足"
3. summary 要指出最关键的差异点
4. 只输出 JSON
"""


# ============================================================
# 功能分析工具
# ============================================================

class FeatureAnalyzer:
    """功能对比分析器

    从 CompetitorProfile 列表中提取功能信息，构建对比矩阵。
    """

    @staticmethod
    def extract_features(profile: CompetitorProfile) -> dict[str, str]:
        """从竞品画像中提取功能摘要

        Returns:
            {功能名: 功能描述}
        """
        features = {}
        for f in profile.core_features:
            status = "✓" if f.supported else "✗"
            features[f.name] = f"{status} {f.description or f.notes}".strip()
        return features

    @staticmethod
    def build_comparison_data(
        profiles: list[CompetitorProfile],
    ) -> str:
        """将多个竞品画像转为 LLM 可读的对比数据文本"""
        parts = []
        for p in profiles:
            parts.append(f"## {p.name} ({p.company})")
            parts.append(f"分类: {p.category}")
            parts.append(f"简介: {p.description}")
            parts.append(f"目标市场: {p.target_market}")
            parts.append("\n### 核心功能")
            for f in p.core_features:
                parts.append(f"- {f.name}: {f.description} ({'支持' if f.supported else '不支持'})")
            if p.pricing:
                parts.append(f"\n### 定价: {p.pricing.model} | {p.pricing.starting_price}")
            parts.append("\n### 优势")
            for s in p.strengths:
                parts.append(f"- {s.content}")
            parts.append("\n### 劣势")
            for w in p.weaknesses:
                parts.append(f"- {w.content}")
            parts.append("")
        return "\n".join(parts)

    @staticmethod
    def build_matrix_from_llm(
        llm_response: str,
        competitors: list[str],
        dimensions: list[str],
        evidence_list: list[Evidence],
    ) -> FeatureMatrix:
        """将 LLM 输出解析为 FeatureMatrix

        Args:
            llm_response: LLM 返回的 JSON 字符串
            competitors: 竞品名称列表
            dimensions: 对比维度列表
            evidence_list: 证据列表

        Returns:
            FeatureMatrix 实例
        """
        import json
        import re

        # 解析 JSON
        text = llm_response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    logger.warning(f"正则提取的非 JSON 内容: {match.group(0)[:100]}")
                    return FeatureMatrix(
                        competitors=competitors,
                        dimensions=dimensions,
                        matrix={},
                        summary="LLM 输出解析失败，需人工补充",
                        evidence_list=evidence_list,
                    )
            else:
                logger.warning(f"无法解析 LLM 输出: {text[:200]}")
                return FeatureMatrix(
                    competitors=competitors,
                    dimensions=dimensions,
                    matrix={},
                    summary="LLM 输出解析失败，需人工补充",
                    evidence_list=evidence_list,
                )

        return FeatureMatrix(
            competitors=competitors,
            dimensions=dimensions,
            matrix=data.get("matrix", {}),
            summary=data.get("summary", ""),
            evidence_list=evidence_list,
        )
