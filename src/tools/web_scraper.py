"""
网页抓取工具

基于 httpx 的轻量级网页内容抓取器。
用于从搜索结果中的 URL 获取详细页面内容。
"""

import httpx
from loguru import logger


class WebScraperTool:
    """网页抓取工具

    抓取指定 URL 的网页内容，提取纯文本。

    使用方式：
        scraper = WebScraperTool()
        content = scraper.fetch("https://example.com/page")
    """

    def __init__(self, timeout: int = 30, user_agent: str = ""):
        self.timeout = timeout
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )

    def fetch(self, url: str) -> dict:
        """抓取网页内容

        Args:
            url: 目标网页 URL

        Returns:
            {
                "url": str,
                "status_code": int,
                "title": str,
                "text": str,        # 提取的纯文本
                "html": str,        # 原始 HTML（截断）
                "error": str | None,
            }
        """
        logger.info(f"抓取: {url}")
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                response = client.get(
                    url,
                    headers={"User-Agent": self.user_agent},
                )
                response.raise_for_status()

                html = response.text
                text = self._extract_text(html)
                title = self._extract_title(html)

                logger.info(f"抓取成功: {url} → {len(text)} 字符")
                return {
                    "url": url,
                    "status_code": response.status_code,
                    "title": title,
                    "text": text[:10000],    # 截断过长内容
                    "html": html[:5000],     # 保留部分 HTML 用于调试
                    "error": None,
                }
        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP 错误 {e.response.status_code}: {url}")
            return self._error_result(url, f"HTTP {e.response.status_code}")
        except httpx.RequestError as e:
            logger.warning(f"请求失败: {url} - {e}")
            return self._error_result(url, str(e))
        except Exception as e:
            logger.error(f"未知错误: {url} - {e}")
            return self._error_result(url, str(e))

    def fetch_multiple(self, urls: list[str]) -> list[dict]:
        """批量抓取（顺序执行，避免触发反爬）"""
        results = []
        for url in urls:
            result = self.fetch(url)
            results.append(result)
        return results

    # --- 内部方法 ---

    @staticmethod
    def _extract_text(html: str) -> str:
        """从 HTML 中提取纯文本（简易实现）"""
        import re
        # 移除 script 和 style 标签
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # 移除 HTML 标签
        text = re.sub(r'<[^>]+>', ' ', text)
        # 合并空白字符
        text = re.sub(r'\s+', ' ', text)
        # 解码常见 HTML 实体
        text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
        return text.strip()

    @staticmethod
    def _extract_title(html: str) -> str:
        """提取页面标题"""
        import re
        match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _error_result(url: str, error: str) -> dict:
        return {
            "url": url,
            "status_code": 0,
            "title": "",
            "text": "",
            "html": "",
            "error": error,
        }
