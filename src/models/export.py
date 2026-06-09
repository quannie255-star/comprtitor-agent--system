"""
报告导出器

将 Markdown 报告转换为 HTML（浏览器可直接打印为 PDF）。
避免 WeasyPrint 在 Windows 上的 GTK 依赖问题。
"""

from core.schema import StructuredReport


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans SC', sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; color: #1a1a2e; line-height: 1.8; }}
  h1 {{ color: #1E6FE9; border-bottom: 3px solid #1E6FE9; padding-bottom: 12px; }}
  h2 {{ color: #1E6FE9; margin-top: 36px; border-bottom: 1px solid #e0e0e0; padding-bottom: 8px; }}
  h3 {{ color: #334155; margin-top: 24px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
  th, td {{ border: 1px solid #e0e0e0; padding: 10px 14px; text-align: left; }}
  th {{ background: #F0F4FF; font-weight: 600; }}
  .meta {{ color: #6B7280; font-size: 0.9em; }}
  .source {{ background: #E8F0FE; color: #1E6FE9; padding: 1px 6px; border-radius: 4px; font-family: monospace; font-size: 0.85em; }}
  .swot-strength {{ color: #10B981; }}
  .swot-weakness {{ color: #EF4444; }}
  .swot-opportunity {{ color: #1E6FE9; }}
  .swot-threat {{ color: #F59E0B; }}
  @media print {{
    body {{ margin: 0; }}
    h2 {{ page-break-before: avoid; }}
  }}
</style>
</head>
<body>
{body}
</body>
</html>"""


class ReportExporter:
    """报告导出器 — Markdown → HTML"""

    @staticmethod
    def markdown_to_html(markdown_text: str) -> str:
        """将 Markdown 转为 HTML 正文（不含 head/style）"""
        try:
            import markdown
            return markdown.markdown(
                markdown_text,
                extensions=["tables", "fenced_code", "codehilite", "toc"],
            )
        except ImportError:
            return _simple_md_to_html(markdown_text)

    @staticmethod
    def render_html(report: StructuredReport) -> str:
        """渲染完整 HTML 报告"""
        from models.report import ReportRenderer
        renderer = ReportRenderer()
        md_body = renderer.render_full(report)
        html_body = ReportExporter.markdown_to_html(md_body)
        return HTML_TEMPLATE.format(
            title=report.title,
            body=html_body,
        )

    @staticmethod
    def save_html(report: StructuredReport, output_dir: str = "./outputs") -> str:
        """保存 HTML 报告到文件"""
        import os
        os.makedirs(output_dir, exist_ok=True)
        filename = f"report_{report.generated_at.strftime('%Y%m%d_%H%M%S')}_{report.trace_id[:8]}.html"
        filepath = os.path.join(output_dir, filename)
        html = ReportExporter.render_html(report)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        return filepath


def _simple_md_to_html(md: str) -> str:
    """简易 Markdown → HTML（无需 markdown 库）"""
    import re
    html = md
    # 标题
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
    # 粗体 / 斜体
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
    # 表格
    html = re.sub(r'^\|(.+)\|$', r'<tr><td>\1</td></tr>', html, flags=re.MULTILINE)
    html = html.replace('</td></tr>\n<tr><td>', '</td></tr><tr><td>')
    html = html.replace('</td></tr>\n<tr><td>---', '<tr><th>')
    # 段落
    html = re.sub(r'\n\n', r'</p><p>', html)
    html = f'<p>{html}</p>'
    # 链接
    html = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', html)
    return html
