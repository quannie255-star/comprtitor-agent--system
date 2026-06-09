"""
市场洞察分析模型

基于竞品数据生成 SWOT 分析、市场定位判断、差异化洞察和趋势分析。
包含分析 Prompt 模板和洞察构建工具。
"""

from loguru import logger

from core.schema import (
    AnnotatedFinding,
    CompetitorProfile,
    Evidence,
    MarketInsight,
    SWOTItem,
)


# ============================================================
# 分析 Prompt 模板
# ============================================================

MARKET_INSIGHT_PROMPT = """你是一位资深的行业分析师。请基于以下竞品信息，生成市场洞察分析。

## 竞品信息
{competitor_data}

## 行业背景
{industry_context}

## 输出要求
请以 JSON 格式输出（只输出 JSON）：

```json
{{
  "swot": {{
    "strengths": ["产品优势1", "产品优势2"],
    "weaknesses": ["产品劣势1", "产品劣势2"],
    "opportunities": ["市场机会1", "市场机会2"],
    "threats": ["竞争威胁1", "竞争威胁2"]
  }},
  "market_position": "一句话描述该产品在市场中的定位",
  "differentiation_points": [
    "差异化点1：具体说明与竞品的差异",
    "差异化点2：具体说明与竞品的差异"
  ],
  "trends": [
    "趋势1：该品类的发展趋势判断",
    "趋势2：该品类的发展趋势判断"
  ]
}}
```

## 规则
1. SWOT 的每一项必须基于原文信息，不得凭空编造
2. opportunities 和 threats 聚焦行业层面，非产品层面
3. differentiation_points 必须指出与同类产品的具体差异
4. trends 关注技术趋势、用户需求变化、商业模式演进
5. 只输出 JSON
"""


# ============================================================
# 市场洞察构建器
# ============================================================

class MarketInsightBuilder:
    """市场洞察构建器

    从 LLM 输出和证据列表构建 MarketInsight 实例。
    """

    @staticmethod
    def build_context(
        profile: CompetitorProfile,
        industry_notes: str = "",
    ) -> str:
        """构建行业背景说明（LLM Prompt 的一部分）

        Args:
            profile: 竞品画像
            industry_notes: 手动补充的行业背景

        Returns:
            格式化的行业背景文本
        """
        parts = [f"产品类别: {profile.category}"]
        if profile.target_market:
            parts.append(f"目标市场: {profile.target_market}")
        if industry_notes:
            parts.append(f"补充信息: {industry_notes}")
        return "\n".join(parts)

    @staticmethod
    def from_llm_response(
        llm_response: str,
        competitor_name: str,
        evidence_list: list[Evidence],
    ) -> MarketInsight:
        """从 LLM 输出构建 MarketInsight

        Args:
            llm_response: LLM 原始输出
            competitor_name: 竞品名称
            evidence_list: 证据列表

        Returns:
            MarketInsight 实例
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
                    data = {}
            else:
                logger.warning(f"无法解析 LLM 输出: {text[:200]}")
                data = {}

        swot_data = data.get("swot", {})

        # 使用第一条 evidence 作为默认证据
        default_evidence = evidence_list[0] if evidence_list else None

        def make_findings(items: list[str]) -> list[AnnotatedFinding]:
            if default_evidence:
                return [AnnotatedFinding(content=item, evidence=default_evidence) for item in items]
            return []

        return MarketInsight(
            competitor_name=competitor_name,
            swot=SWOTItem(
                strengths=swot_data.get("strengths", []),
                weaknesses=swot_data.get("weaknesses", []),
                opportunities=swot_data.get("opportunities", []),
                threats=swot_data.get("threats", []),
            ),
            market_position=data.get("market_position", ""),
            differentiation_points=make_findings(data.get("differentiation_points", [])),
            trends=make_findings(data.get("trends", [])),
            evidence_list=evidence_list,
        )
