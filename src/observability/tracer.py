"""
LLM 调用链追踪器 (LLM Tracer)

类似 APM 但针对大模型调用：
  - 每次 LLM 调用生成 span（trace_id + call_id + latency + tokens）
  - 输入/输出摘要（用于审计回溯）
  - 调用链时间线（Agent → LLM → 返回）

用法：
    tracer = LLMTracer()
    tracer.start_call(agent="collector", model="gpt-4o", prompt="...")
    # ... LLM call ...
    tracer.end_call(output="...", tokens_used=1500)
"""

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import uuid4


@dataclass
class LLMCallSpan:
    """单次 LLM 调用的完整记录"""

    call_id: str
    trace_id: str
    agent_name: str
    provider: str
    model: str

    # 输入输出摘要
    prompt_summary: str = ""       # 截断后的 prompt 前 200 字符
    output_summary: str = ""       # 截断后的 response 前 200 字符

    # 性能指标
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    latency_ms: float = 0.0

    # Token 估算
    input_tokens: int = 0          # 实际或估算
    output_tokens: int = 0

    # 状态
    success: bool = True
    error_message: str = ""

    def to_dict(self) -> dict:
        return {
            "call_id": self.call_id,
            "trace_id": self.trace_id,
            "agent_name": self.agent_name,
            "provider": self.provider,
            "model": self.model,
            "prompt_summary": self.prompt_summary,
            "output_summary": self.output_summary,
            "started_at": self.started_at.isoformat() if self.started_at else "",
            "finished_at": self.finished_at.isoformat() if self.finished_at else "",
            "latency_ms": round(self.latency_ms, 1),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "success": self.success,
            "error_message": self.error_message,
        }


class LLMTracer:
    """LLM 调用链追踪器

    嵌入在 BaseAgent._invoke_llm 中，对 Agent 代码零侵入。
    保存全量调用链到内存，可通过 to_log() 持久化。

    使用方式：
        tracer = LLMTracer(trace_id="...")
        tracer.start(agent="collector", model="gpt-4o", prompt=prompt, provider="openai")
        # LLM 调用
        tracer.end(output=response, tokens=500)
    """

    def __init__(self, trace_id: str = ""):
        self.trace_id = trace_id or str(uuid4())
        self.spans: list[LLMCallSpan] = []
        self._active: dict[str, LLMCallSpan] = {}  # 支持并发（预留）

    def start(
        self,
        *,
        agent_name: str,
        model: str,
        prompt: str,
        provider: str = "openai",
    ) -> str:
        """开始一次 LLM 调用追踪，返回 call_id"""
        call_id = str(uuid4())[:8]
        span = LLMCallSpan(
            call_id=call_id,
            trace_id=self.trace_id,
            agent_name=agent_name,
            provider=provider,
            model=model,
            prompt_summary=prompt[:200].replace("\n", " ") if prompt else "",
            started_at=datetime.now(),
        )
        span._start_time = time.time()  # type: ignore[attr-defined]
        self._active[call_id] = span
        return call_id

    def end(
        self,
        call_id: str,
        *,
        output: str,
        tokens_used: int = 0,
        success: bool = True,
        error: str = "",
    ) -> LLMCallSpan:
        """结束一次 LLM 调用追踪"""
        span = self._active.pop(call_id, None)
        if span is None:
            # 兼容直接调用（未 start 先 end）
            span = LLMCallSpan(
                call_id=call_id,
                trace_id=self.trace_id,
                agent_name="unknown",
                provider="unknown",
                model="unknown",
                started_at=datetime.now(),
            )

        span.finished_at = datetime.now()
        span.latency_ms = (time.time() - getattr(span, '_start_time', time.time())) * 1000
        span.output_summary = output[:200].replace("\n", " ") if output else ""
        span.success = success
        span.error_message = error

        # Token 估算（如果没有精确值，按经验值估算）
        span.input_tokens = max(len(span.prompt_summary) // 3, 1)
        span.output_tokens = tokens_used if tokens_used > 0 else max(len(span.output_summary) // 3, 1)

        self.spans.append(span)
        return span

    def end_with_response(
        self,
        call_id: str,
        *,
        response,  # LangChain AIMessage 或 str
        success: bool = True,
    ) -> LLMCallSpan:
        """从 LangChain response 中提取 tokens + output"""
        output = ""
        tokens = 0

        if hasattr(response, 'content'):
            output = response.content or ""
        elif isinstance(response, str):
            output = response

        if hasattr(response, 'response_metadata'):
            usage = response.response_metadata.get("token_usage", {}) or response.response_metadata.get("usage", {})
            tokens = usage.get("total_tokens", 0)

        return self.end(call_id, output=output, tokens_used=tokens, success=success)

    def to_log(self) -> list[dict]:
        """导出为 JSON 可序列化的日志列表"""
        return [s.to_dict() for s in self.spans]

    def summary(self) -> dict:
        """调用链摘要"""
        if not self.spans:
            return {"total_calls": 0}

        succeeded = [s for s in self.spans if s.success]
        total_tokens = sum(s.input_tokens + s.output_tokens for s in self.spans)
        avg_latency = sum(s.latency_ms for s in self.spans) / len(self.spans) if self.spans else 0
        models_used = list({s.model for s in self.spans})

        return {
            "total_calls": len(self.spans),
            "success_rate": f"{len(succeeded)}/{len(self.spans)}",
            "total_tokens": total_tokens,
            "avg_latency_ms": round(avg_latency, 1),
            "models_used": models_used,
        }
