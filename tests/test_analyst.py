"""
分析 Agent 单元测试

覆盖：
1. FeatureAnalyzer 功能提取
2. FeatureAnalyzer 对比数据构建
3. FeatureAnalyzer LLM 输出解析 → FeatureMatrix
4. MarketInsightBuilder 背景构建
5. MarketInsightBuilder LLM 输出解析 → MarketInsight
6. AnalystAgent.execute 完整流程（mock LLM）
7. 分析结果溯源验证
"""

import json
from unittest.mock import MagicMock

import pytest

from agents.analyst import AnalystAgent
from core.schema import (
    AnnotatedFinding,
    CompetitorProfile,
    Feature,
    FeatureMatrix,
    MarketInsight,
    Pricing,
)
from models.feature import FeatureAnalyzer
from models.market import MarketInsightBuilder

# ============================================================
# 共享 Fixtures
# ============================================================

@pytest.fixture
def sample_profiles(sample_evidence):
    """创建两个示例竞品画像"""
    def _make_profile(name, company, category):
        return CompetitorProfile(
            name=name,
            company=company,
            website=f"https://{name.lower()}.com",
            category=category,
            description=f"{name} 产品简介",
            target_market="团队协作",
            core_features=[
                Feature(name="实时协作", description="多人同时编辑", supported=True, evidence=sample_evidence),
                Feature(name="API 开放", description="提供 REST API", supported=(name != "ProductB"), evidence=sample_evidence),
            ],
            pricing=Pricing(model="订阅制", starting_price="$10/月", source=sample_evidence),
            strengths=[AnnotatedFinding(content="界面易用", evidence=sample_evidence)],
            weaknesses=[AnnotatedFinding(content="离线支持弱", evidence=sample_evidence)],
            data_sources=[sample_evidence],
        )
    return [
        _make_profile("ProductA", "公司A", "协作工具"),
        _make_profile("ProductB", "公司B", "协作工具"),
    ]


@pytest.fixture
def mock_llm():
    """模拟 LLM 响应"""
    llm = MagicMock()
    # 功能对比响应
    comparison_response = json.dumps({
        "matrix": {
            "核心功能完整性": {"ProductA": "功能齐全", "ProductB": "基础功能"},
            "集成生态": {"ProductA": "API 丰富", "ProductB": "API 有限"},
        },
        "summary": "ProductA 在功能完整性和集成生态上优于 ProductB。",
        "key_findings": ["ProductA 功能更全", "ProductB 定价更低"],
    }, ensure_ascii=False)

    # 市场洞察响应
    insight_response = json.dumps({
        "swot": {
            "strengths": ["品牌知名度高", "技术实力强"],
            "weaknesses": ["本地化不足", "价格偏高"],
            "opportunities": ["新兴市场需求增长", "AI 功能需求爆发"],
            "threats": ["开源替代品崛起", "大厂入场竞争"],
        },
        "market_position": "协作工具领域领导者",
        "differentiation_points": ["一体化体验优于竞品", "API 生态更丰富"],
        "trends": ["AI 辅助功能成为标配", "移动端体验要求提高"],
    }, ensure_ascii=False)

    # 每次调用返回不同内容（第1次对比，第2-3次各 profile 的洞察）
    llm.invoke.side_effect = [
        MagicMock(content=comparison_response),
        MagicMock(content=insight_response),
        MagicMock(content=insight_response),  # 2 个 profiles → 需要 2 次洞察
    ]
    return llm


# ============================================================
# FeatureAnalyzer
# ============================================================

class TestFeatureAnalyzer:
    def test_extract_features(self, sample_profiles):
        features = FeatureAnalyzer.extract_features(sample_profiles[0])
        assert "实时协作" in features
        assert "API 开放" in features

    def test_build_comparison_data(self, sample_profiles):
        text = FeatureAnalyzer.build_comparison_data(sample_profiles)
        assert "ProductA" in text
        assert "ProductB" in text
        assert "界面易用" in text  # strengths
        assert "离线支持弱" in text  # weaknesses

    def test_build_matrix_from_llm(self, sample_evidence):
        response = json.dumps({
            "matrix": {"价格": {"A": "低", "B": "高"}},
            "summary": "A 更便宜",
        }, ensure_ascii=False)
        fm = FeatureAnalyzer.build_matrix_from_llm(
            response,
            competitors=["A", "B"],
            dimensions=["价格"],
            evidence_list=[sample_evidence],
        )
        assert isinstance(fm, FeatureMatrix)
        assert fm.competitors == ["A", "B"]
        assert fm.matrix["价格"]["A"] == "低"

    def test_build_matrix_with_markdown_fence(self, sample_evidence):
        response = '```json\n{"matrix": {"功能": {"X": "好"}}, "summary": "OK"}\n```'
        fm = FeatureAnalyzer.build_matrix_from_llm(
            response,
            competitors=["X"],
            dimensions=["功能"],
            evidence_list=[sample_evidence],
        )
        assert fm.summary == "OK"


# ============================================================
# MarketInsightBuilder
# ============================================================

class TestMarketInsightBuilder:
    def test_build_context(self, sample_profiles):
        context = MarketInsightBuilder.build_context(
            sample_profiles[0],
            industry_notes="2025 年协作工具市场规模 200 亿美元",
        )
        assert "协作工具" in context
        assert "200 亿美元" in context

    def test_from_llm_response(self, sample_evidence):
        response = json.dumps({
            "swot": {
                "strengths": ["S1"],
                "weaknesses": ["W1"],
                "opportunities": ["O1"],
                "threats": ["T1"],
            },
            "market_position": "领导者",
            "differentiation_points": ["差异1", "差异2"],
            "trends": ["趋势1"],
        }, ensure_ascii=False)
        mi = MarketInsightBuilder.from_llm_response(
            response,
            competitor_name="TestProduct",
            evidence_list=[sample_evidence],
        )
        assert isinstance(mi, MarketInsight)
        assert mi.competitor_name == "TestProduct"
        assert mi.swot.strengths == ["S1"]
        assert mi.market_position == "领导者"
        assert len(mi.differentiation_points) == 2
        assert isinstance(mi.differentiation_points[0], AnnotatedFinding)

    def test_from_llm_with_markdown_fence(self, sample_evidence):
        response = '```json\n{"swot": {"strengths":["S"],"weaknesses":[],"opportunities":[],"threats":[]}, "market_position": "M", "differentiation_points": [], "trends": []}\n```'
        mi = MarketInsightBuilder.from_llm_response(
            response,
            competitor_name="X",
            evidence_list=[sample_evidence],
        )
        assert mi.market_position == "M"


# ============================================================
# AnalystAgent
# ============================================================

class TestAnalystAgent:
    @pytest.fixture
    def analyst(self, message_bus, mock_llm):
        return AnalystAgent(
            message_bus=message_bus,
            llm=mock_llm,
            config={
                "agents": {
                    "analyst": {
                        "comparison_dimensions": ["核心功能完整性", "集成生态"],
                    }
                }
            },
        )

    def test_execute_full_flow(self, analyst, message_bus, sample_state, sample_profiles):
        """完整分析流程：profiles → feature_matrix + market_insights"""
        # 将 profiles 放入 state
        state = {
            **sample_state,
            "competitor_profiles": [p.model_dump(mode="json") for p in sample_profiles],
            "source_pool": [sample_profiles[0].data_sources[0].model_dump(mode="json")],
        }

        result = analyst.execute(state)

        # 验证 feature_matrix
        assert "feature_matrix" in result
        fm = result["feature_matrix"]
        assert isinstance(fm, dict)
        assert "competitors" in fm
        assert "ProductA" in fm["competitors"]

        # 验证 market_insights
        assert "market_insights" in result
        assert len(result["market_insights"]) == 2  # 每个 profile 一条

    def test_execute_raises_without_profiles(self, analyst):
        """缺少 competitor_profiles 时抛异常"""
        with pytest.raises(ValueError, match="competitor_profiles"):
            analyst.execute({"competitor_profiles": []})

    def test_sends_message_to_writer(self, analyst, message_bus, sample_state, sample_profiles):
        """分析完成后向 Writer 发送消息"""
        received = []
        message_bus.subscribe("writer", lambda m: received.append(m))

        state = {
            **sample_state,
            "competitor_profiles": [p.model_dump(mode="json") for p in sample_profiles],
            "source_pool": [sample_profiles[0].data_sources[0].model_dump(mode="json")],
        }
        analyst.execute(state)

        assert len(received) == 1
        assert received[0].sender == "analyst"
        assert "feature_matrix" in received[0].payload

    def test_execution_log_traceability(self, analyst, sample_state, sample_profiles):
        """每步执行都有日志记录"""
        state = {
            **sample_state,
            "competitor_profiles": [p.model_dump(mode="json") for p in sample_profiles],
            "source_pool": [sample_profiles[0].data_sources[0].model_dump(mode="json")],
        }
        analyst.execute(state)

        log = analyst.get_execution_log()
        actions = [s["action"] for s in log]
        assert "analysis_start" in actions
        assert "analysis_complete" in actions

    def test_agent_name(self, analyst):
        assert analyst.agent_name == "analyst"
