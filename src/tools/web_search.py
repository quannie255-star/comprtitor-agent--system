"""
网络搜索工具

封装 Tavily Search API，提供统一的搜索接口。
后续可扩展 DuckDuckGo 作为免费 fallback。
"""

from typing import Optional

from loguru import logger


class WebSearchTool:
    """网络搜索工具

    使用 Tavily Search API 进行网络搜索，返回结构化结果列表。

    使用方式：
        search = WebSearchTool(api_key="...")
        results = search.search("Notion 产品功能介绍", max_results=5)
    """

    def __init__(self, api_key: str = "", provider: str = "tavily"):
        self.api_key = api_key
        self.provider = provider
        self._client = None

    def _get_client(self):
        """懒加载 Tavily 客户端"""
        if self._client is None and self.provider == "tavily":
            try:
                from tavily import TavilyClient
                self._client = TavilyClient(api_key=self.api_key)
            except ImportError:
                logger.error("tavily-python 未安装，请执行: pip install tavily-python")
                raise
            except Exception as e:
                logger.error(f"Tavily 客户端初始化失败: {e}")
                raise
        return self._client

    def search(
        self,
        query: str,
        max_results: int = 5,
        include_domains: Optional[list[str]] = None,
        search_depth: str = "advanced",
    ) -> list[dict]:
        """执行搜索

        Args:
            query: 搜索关键词
            max_results: 最大返回结果数
            include_domains: 限定搜索域名（可选）
            search_depth: 搜索深度 basic / advanced

        Returns:
            搜索结果列表，每条包含:
              - title: 标题
              - url: 链接
              - content: 摘要内容
              - score: 相关度评分
              - raw_content: 原始内容（advanced 模式下更丰富）
        """
        if not self.api_key:
            logger.warning("Search API key 未配置，返回模拟结果")
            return self._mock_search(query, max_results)

        client = self._get_client()
        try:
            response = client.search(
                query=query,
                max_results=max_results,
                include_domains=include_domains or [],
                search_depth=search_depth,
            )
            results = []
            for item in response.get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("content", ""),
                    "score": item.get("score", 0.0),
                    "raw_content": item.get("raw_content", ""),
                })
            logger.info(f"搜索完成: '{query}' → {len(results)} 条结果")
            return results
        except Exception as e:
            logger.error(f"搜索失败: {e}")
            return self._mock_search(query, max_results)

    def _mock_search(self, query: str, max_results: int) -> list[dict]:
        """Mock 搜索（用于无 API Key 时的开发和测试）"""
        logger.info(f"[Mock] 模拟搜索: '{query}'")
        return [
            {
                "title": f"{query} - 官方产品页面",
                "url": f"https://example.com/products/{query.replace(' ', '-').lower()}",
                "content": f"这是关于 {query} 的模拟搜索结果。包含产品功能介绍、定价信息等。",
                "score": 0.95,
                "raw_content": "",
            },
            {
                "title": f"{query} 评测与分析",
                "url": f"https://example-review.com/{query.replace(' ', '-').lower()}",
                "content": f"{query} 的详细评测，涵盖核心功能、优缺点、定价对比。",
                "score": 0.82,
                "raw_content": "",
            },
            {
                "title": f"{query} 竞品对比",
                "url": f"https://example.com/compare/{query.replace(' ', '-').lower()}",
                "content": f"{query} 与同类产品的功能对比分析。",
                "score": 0.71,
                "raw_content": "",
            },
        ][:max_results]
