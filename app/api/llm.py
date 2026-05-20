"""
D2-1: LLM 调试接口
POST /api/v1/llm/chat — 直接调用 LLM，用于 curl 验证和内部测试。
支持：
- messages 数组（OpenAI 格式）
- force_model 强制模型
- 返回完整 LLMResult（含 model_used / latency_ms / fallback_used）
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional
from loguru import logger
import uuid

from services.llm import chat as llm_chat

router = APIRouter()


class ChatMessage(BaseModel):
    role: str  # system / user / assistant
    content: str


class LLMChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    force_model: Optional[str] = None
    temperature: float = 0.85
    max_tokens: int = Field(default=800, ge=1, le=4000)


@router.post(
    "/llm/chat",
    summary="LLM 直接调用（调试 / 内部用）",
)
async def llm_chat_endpoint(
    body: LLMChatRequest,
    request: Request,
):
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4())[:16].replace("-", ""))
    log = logger.bind(trace_id=trace_id, force_model=body.force_model)
    log.info(f"llm.chat.request messages={len(body.messages)}")

    messages = [m.model_dump() for m in body.messages]

    result = await llm_chat(
        messages=messages,
        trace_id=trace_id,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        force_model=body.force_model,
    )

    log.info(
        f"llm.chat.complete model={result.model_used} fallback={result.fallback_used} latency={result.latency_ms:.0f}ms"
    )

    status = 200 if not result.error else 503
    return JSONResponse(
        status_code=status,
        content={
            "content": result.content,
            "model_used": result.model_used,
            "usage": result.usage,
            "latency_ms": round(result.latency_ms, 1),
            "fallback_used": result.fallback_used,
            "error": result.error,
            "trace_id": trace_id,
        },
    )
