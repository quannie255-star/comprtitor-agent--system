"""
FastAPI REST API

提供竞品分析系统的 HTTP API 端点。
启动方式：
    uvicorn src.api.api:app --reload --port 8000
"""

import os
import sys
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from core.orchestrator import Orchestrator
from models.export import ReportExporter

app = FastAPI(
    title="竞品分析 Agent 协作系统 API",
    description="AI 驱动的多 Agent 竞品分析服务",
    version="0.1.0",
)


# ============================================================
# 请求/响应模型
# ============================================================

class AnalysisRequest(BaseModel):
    target_products: list[str] = Field(
        default=["Notion"],
        description="竞品名称列表，1-3 个",
        min_length=1,
        max_length=3,
    )
    dimensions: list[str] = Field(
        default=["核心功能", "定价策略", "用户体验", "市场定位"],
        description="分析维度",
    )
    format: str = Field(default="markdown", description="输出格式: markdown / html")


class AnalysisResponse(BaseModel):
    trace_id: str
    report: str
    format: str
    profiles_count: int
    review_score: float
    review_passed: bool


# ============================================================
# 端点
# ============================================================

@app.get("/")
def root():
    return {"service": "竞品分析 Agent 协作系统", "version": "0.1.0", "docs": "/docs"}


@app.post("/api/v1/analysis", response_model=AnalysisResponse)
def run_analysis(req: AnalysisRequest):
    """执行竞品分析"""
    config = {
        "llm": {
            "provider": "openai",
            "model": os.getenv("LLM_MODEL", "gpt-4o"),
            "api_key": os.getenv("LLM_API_KEY", ""),
            "api_base": os.getenv("LLM_API_BASE", ""),
        },
        "search": {"api_key": os.getenv("TAVILY_API_KEY", "")},
        "agents": {
            "analyst": {"comparison_dimensions": req.dimensions},
            "reviewer": {"max_review_rounds": 3},
        },
    }

    try:
        orch = Orchestrator(config)
        result = orch.run(
            target_product=req.target_products[0],
            target_products=req.target_products,
            analysis_dimensions=req.dimensions,
            use_langgraph=False,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    report_md = result.get("report", "")
    review = result.get("review_result", {})

    if req.format == "html":
        from models.export import ReportExporter
        report = ReportExporter.markdown_to_html(report_md)
        report = ReportExporter.HTML_TEMPLATE.format(
            title=f"{', '.join(req.target_products)} 竞品分析报告",
            body=report,
        )
    else:
        report = report_md

    return AnalysisResponse(
        trace_id=orch.trace_id,
        report=report,
        format=req.format,
        profiles_count=len(result.get("competitor_profiles", [])),
        review_score=review.get("score", 0) if isinstance(review, dict) else 0,
        review_passed=review.get("passed", False) if isinstance(review, dict) else False,
    )


@app.get("/api/v1/health")
def health():
    return {"status": "ok"}
