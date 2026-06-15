"""
采集 Agent 单元测试

覆盖：
1. WebSearchTool mock 搜索
2. WebScraperTool 抓取（mock HTTP）
3. DataParser JSON 解析
4. DataParser parse_to_profile（无 LLM 降级）
5. CollectorAgent.execute 完整流程
6. source_pool 构建与溯源验证
"""


import pytest

from agents.collector import CollectorAgent
from tools.data_parser import DataParser
from tools.web_scraper import WebScraperTool
from tools.web_search import WebSearchTool

# ============================================================
# WebSearchTool
# ============================================================

class TestWebSearchTool:
    def test_mock_search_no_api_key(self):
        """无 API Key 时使用 mock 结果"""
        tool = WebSearchTool(api_key="")
        results = tool.search("Notion", max_results=3)
        assert len(results) == 3
        assert "url" in results[0]
        assert "title" in results[0]

    def test_mock_search_contains_query_term(self):
        tool = WebSearchTool(api_key="")
        results = tool.search("Slack")
        for r in results:
            assert "Slack" in r["title"] or "Slack" in r["content"] or "slack" in r["url"]


# ============================================================
# WebScraperTool
# ============================================================

class TestWebScraperTool:
    def test_fetch_mock(self):
        """使用真实的 HTTP 抓取（但目标可能是不可达的 mock URL）"""
        scraper = WebScraperTool(timeout=5)
        result = scraper.fetch("https://httpbin.org/status/404")
        # 404 也算"成功抓取"，但内容为空
        assert result["url"] == "https://httpbin.org/status/404"

    def test_fetch_invalid_url(self):
        scraper = WebScraperTool(timeout=5)
        result = scraper.fetch("https://this-domain-does-not-exist-12345.com")
        assert result["error"] is not None
        assert result["text"] == ""

    def test_extract_text_basic(self):
        html = "<html><head><title>Test</title></head><body><p>Hello World</p></body></html>"
        text = WebScraperTool._extract_text(html)
        assert "Hello World" in text
        assert "Test" in text

    def test_extract_text_strips_scripts(self):
        html = "<html><script>console.log('x')</script><body><p>Visible</p></body></html>"
        text = WebScraperTool._extract_text(html)
        assert "console.log" not in text
        assert "Visible" in text


# ============================================================
# DataParser
# ============================================================

class TestDataParser:
    def test_build_prompt(self):
        prompt = DataParser.build_prompt("Notion", "Notion 是一款协作知识库工具...")
        assert "Notion" in prompt
        assert "协作知识库" in prompt

    def test_parse_json_response_clean(self):
        """正常 JSON 解析"""
        data = DataParser.parse_json_response('{"name": "Test", "company": "Inc"}')
        assert data["name"] == "Test"

    def test_parse_json_response_with_markdown_fence(self):
        """带 Markdown 代码块的 JSON"""
        response = '```json\n{"name": "Test"}\n```'
        data = DataParser.parse_json_response(response)
        assert data["name"] == "Test"

    def test_parse_json_response_fallback(self):
        """JSON 嵌入在文本中"""
        response = '根据分析，产品信息如下：{"name": "Test", "company": "Inc"}，以上为提取结果。'
        data = DataParser.parse_json_response(response)
        assert data["name"] == "Test"

    def test_parse_json_response_invalid(self):
        with pytest.raises(ValueError):
            DataParser.parse_json_response("这不是 JSON")

    def test_parse_to_profile_no_llm(self):
        """LLM 不可用时返回 None — 由 Collector 构建降级 Profile"""
        parser = DataParser()
        profile = parser.parse_to_profile(
            llm=None,
            target_product="Notion",
            raw_text="测试文本",
            source_url="https://example.com",
            source_title="Test",
        )
        assert profile is None


# ============================================================
# CollectorAgent
# ============================================================

class TestCollectorAgent:
    @pytest.fixture
    def collector(self, message_bus):
        return CollectorAgent(
            message_bus=message_bus,
            config={"search": {"api_key": ""}},  # 空 key → mock
        )

    def test_execute_with_mock_search(self, collector, sample_state):
        """使用 mock 搜索完成完整采集流程"""
        result = collector.execute(sample_state)

        # 验证 source_pool
        assert "source_pool" in result
        assert len(result["source_pool"]) > 0
        source = result["source_pool"][0]
        assert "source_url" in source
        assert "source_title" in source

        # 验证 competitor_profiles
        assert "competitor_profiles" in result
        assert len(result["competitor_profiles"]) == 1
        profile_dict = result["competitor_profiles"][0]
        assert profile_dict["name"] is not None

        # 验证执行日志
        log = collector.get_execution_log()
        actions = [step["action"] for step in log]
        assert "search_start" in actions
        assert "scrape_start" in actions
        assert "parse_start" in actions

    def test_execute_raises_without_target(self, collector):
        """缺少 target_product 时抛异常"""
        with pytest.raises(ValueError):
            collector.execute({"target_product": ""})

    def test_sends_message_to_analyst(self, collector, message_bus, sample_state):
        """采集完成后向 Analyst 发送消息"""
        analyst_received = []

        def handler(msg):
            analyst_received.append(msg)

        message_bus.subscribe("analyst", handler)

        collector.execute(sample_state)

        assert len(analyst_received) == 1
        assert analyst_received[0].sender == "collector"
        assert analyst_received[0].msg_type.value == "data_output"
        assert "profile_count" in analyst_received[0].payload

    def test_source_pool_evidence_structure(self, collector, sample_state):
        """验证 source_pool 中每条证据的结构完整性"""
        result = collector.execute(sample_state)

        for source in result["source_pool"]:
            assert "source_id" in source
            assert "source_url" in source
            assert "source_title" in source
            assert "confidence" in source
            assert 0 <= source["confidence"] <= 1

    def test_merge_scraped_content(self):
        """测试搜索+抓取内容合并"""
        search_results = [
            {"title": "T1", "content": "C1", "url": "http://x.com"},
        ]
        scraped = [
            {"title": "T1", "text": "Full content here", "error": None},
        ]
        merged = CollectorAgent._merge_scraped_content(search_results, scraped)
        assert "搜索结果摘要" in merged
        assert "页面内容" in merged
        assert "Full content here" in merged

    def test_agent_name(self, collector):
        assert collector.agent_name == "collector"

    def test_string_iteration_trap_guarded(self, collector, sample_state):
        """防御：传入单字符串不应被拆分为单字符列表"""
        # 模拟有人误把字符串当列表传入
        state = {**sample_state, "target_products": "notion"}
        result = collector.execute(state)
        # 应该只有 1 个竞品，而不是 6 个（n, o, t, i, o, n）
        profiles = result.get("competitor_profiles", [])
        assert len(profiles) == 1

    def test_short_names_filtered(self, collector, sample_state):
        """单字符或空字符串应被过滤掉"""
        state = {**sample_state, "target_products": ["n", "", "Notion", "o"]}
        result = collector.execute(state)
        # "n" 和 "o" 长度 < 2 被过滤，"" 被过滤，只剩 "Notion"
        profiles = result.get("competitor_profiles", [])
        assert len(profiles) == 1
