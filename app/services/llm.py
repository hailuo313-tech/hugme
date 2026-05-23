"""
D2-1: Novita AI LLM 客户端
- 异步 httpx 直接调用 Novita AI（/chat/completions，OpenAI 兼容接口）
- 主模型：chat2（Novita AI 核心模型）
- 备用模型：chat2（同一模型，仅超时重试）
- 降级策略：主模型超时（PRIMARY_TIMEOUT=25s）或 5xx 错误 → 自动重试
- 支持流式（stream=False 当前阶段，D2-2 Orchestrator 可扩展）
- 结构化返回：LLMResult（content, model_used, usage, latency_ms, fallback_used）
"""
from __future__ import annotations

import time
from typing import Any

import httpx
from loguru import logger
from pydantic import BaseModel

from core.config import settings


# ── 模型常量 ──────────────────────────────────────────
PRIMARY_MODEL   = "deepseek/deepseek-v4-flash"
FALLBACK_MODEL  = "deepseek/deepseek-v4-flash"
NOVITA_BASE     = "https://api.novita.ai/openai/v1"

PRIMARY_TIMEOUT_S  = 25.0   # 主模型超时：25s
FALLBACK_TIMEOUT_S = 20.0   # 备用模型超时：20s


# ── 返回结构 ──────────────────────────────────────────
class LLMResult(BaseModel):
    content:       str
    model_used:    str
    usage:         dict[str, Any] = {}
    latency_ms:    float
    fallback_used: bool = False
    error:         str | None = None


# ── 内部工具 ──────────────────────────────────────────

def _headers() -> dict[str, str]:
    return {
        "Authorization":  f"Bearer {settings.NOVITA_API_KEY}",
        "Content-Type":   "application/json",
    }


def _build_body(
    messages: list[dict],
    model:    str,
    temperature: float = 0.85,
    max_tokens:  int   = 800,
) -> dict:
    return {
        "model":       model,
        "messages":    messages,
        "temperature": temperature,
        "max_tokens":  max_tokens,
        "stream":      False,
    }


async def _call_once(
    messages:    list[dict],
    model:       str,
    timeout_s:   float,
    trace_id:    str,
) -> tuple[str, dict]:
    """
    单次调用 Novita AI。
    返回 (content, usage_dict)。
    抛出 httpx.TimeoutException 或 RuntimeError（非 2xx）。
    """
    body = _build_body(messages, model)
    url  = f"{NOVITA_BASE}/chat/completions"

    logger.info(f"[{trace_id}] llm.call.start model={model} timeout={timeout_s}s")
    t0 = time.time()

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(url, json=body, headers=_headers())

    latency = (time.time() - t0) * 1000
    logger.info(f"[{trace_id}] llm.call.response model={model} status={resp.status_code} latency={latency:.0f}ms")

    if resp.status_code >= 500:
        raise RuntimeError(f"Novita AI 5xx: {resp.status_code} {resp.text[:200]}")
    if resp.status_code >= 400:
        raise RuntimeError(f"Novita AI 4xx: {resp.status_code} {resp.text[:200]}")

    data    = resp.json()
    content = data["choices"][0]["message"]["content"]
    usage   = data.get("usage", {})
    return content, usage


# ── 公开接口 ──────────────────────────────────────────

async def chat(
    messages:    list[dict],
    trace_id:    str,
    temperature: float = 0.85,
    max_tokens:  int   = 800,
    force_model: str | None = None,
) -> LLMResult:
    """
    主入口：发送消息列表，返回 LLMResult。
    自动降级：PRIMARY 超时或 5xx → FALLBACK。
    force_model 可跳过路由（A/B 实验 / 测试用）。
    """
    if not settings.NOVITA_API_KEY:
        logger.error(f"[{trace_id}] NOVITA_API_KEY not configured")
        return LLMResult(
            content="现在有点忙，稍后再聊好吗？",
            model_used="none",
            latency_ms=0,
            error="API_KEY_MISSING",
        )

    start_ts = time.time()

    # ── 强制指定模型（跳过路由）──────────────────────
    if force_model:
        try:
            content, usage = await _call_once(messages, force_model, PRIMARY_TIMEOUT_S, trace_id)
            return LLMResult(
                content=content,
                model_used=force_model,
                usage=usage,
                latency_ms=(time.time() - start_ts) * 1000,
                fallback_used=False,
            )
        except Exception as e:
            logger.warning(f"[{trace_id}] llm.force_model.fail model={force_model} err={e}")
            return LLMResult(
                content="现在有点忙，稍后再聊好吗？",
                model_used=force_model,
                latency_ms=(time.time() - start_ts) * 1000,
                error=str(e),
            )

    # ── 主模型 ────────────────────────────────────────
    primary_err: str | None = None
    try:
        content, usage = await _call_once(messages, PRIMARY_MODEL, PRIMARY_TIMEOUT_S, trace_id)
        return LLMResult(
            content=content,
            model_used=PRIMARY_MODEL,
            usage=usage,
            latency_ms=(time.time() - start_ts) * 1000,
            fallback_used=False,
        )
    except httpx.TimeoutException as e:
        primary_err = f"timeout: {e}"
        logger.warning(f"[{trace_id}] llm.primary.timeout model={PRIMARY_MODEL} → fallback")
    except RuntimeError as e:
        primary_err = str(e)
        if "5xx" in primary_err:
            logger.warning(f"[{trace_id}] llm.primary.5xx model={PRIMARY_MODEL} → fallback")
        else:
            # 4xx（如余额不足）不降级，直接返回错误
            logger.error(f"[{trace_id}] llm.primary.4xx model={PRIMARY_MODEL} err={primary_err}")
            return LLMResult(
                content="现在有点忙，稍后再聊好吗？",
                model_used=PRIMARY_MODEL,
                latency_ms=(time.time() - start_ts) * 1000,
                error=primary_err,
            )
    except Exception as e:
        primary_err = str(e)
        logger.warning(f"[{trace_id}] llm.primary.error model={PRIMARY_MODEL} err={e} → fallback")

    # ── 备用模型 ──────────────────────────────────────
    logger.info(f"[{trace_id}] llm.fallback.start model={FALLBACK_MODEL} primary_err={primary_err}")
    try:
        content, usage = await _call_once(messages, FALLBACK_MODEL, FALLBACK_TIMEOUT_S, trace_id)
        return LLMResult(
            content=content,
            model_used=FALLBACK_MODEL,
            usage=usage,
            latency_ms=(time.time() - start_ts) * 1000,
            fallback_used=True,
        )
    except Exception as e:
        fallback_err = str(e)
        logger.error(
            f"[{trace_id}] llm.fallback.error model={FALLBACK_MODEL} "
            f"primary_err={primary_err} fallback_err={fallback_err}"
        )
        return LLMResult(
            content="现在有点忙，稍后再聊好吗？",
            model_used=FALLBACK_MODEL,
            latency_ms=(time.time() - start_ts) * 1000,
            fallback_used=True,
            error=f"primary={primary_err}; fallback={fallback_err}",
        )
