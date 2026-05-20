"""
D2-1: LLM 客户端（OpenAI 兼容接口）
- 默认对接 Novita AI：https://api.novita.ai/openai/v1/chat/completions
- 亦可通过 LLM_API_BASE_URL 指向 OpenRouter 等其它兼容网关
- 主/备模型由环境变量 LLM_PRIMARY_MODEL / LLM_FALLBACK_MODEL 配置
- API Key：优先 NOVITA_API_KEY，其次 OPENROUTER_API_KEY（兼容旧配置）
- 降级策略：主模型超时（25s）或 5xx → 自动切备用模型
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from loguru import logger
from pydantic import BaseModel

from core.config import settings


PRIMARY_TIMEOUT_S = 25.0  # 主模型超时：25s
FALLBACK_TIMEOUT_S = 20.0  # 备用模型超时：20s

HTTP_REFERER = "https://hugme2.com"
APP_TITLE = "ERIS Emotional Companion"


def _llm_api_key() -> str:
    return (settings.NOVITA_API_KEY or settings.OPENROUTER_API_KEY or "").strip()


def _llm_base_url() -> str:
    return settings.LLM_API_BASE_URL.rstrip("/")


def _primary_model() -> str:
    return settings.LLM_PRIMARY_MODEL


def _fallback_model() -> str:
    return settings.LLM_FALLBACK_MODEL


# ── 返回结构 ──────────────────────────────────────────
class LLMResult(BaseModel):
    content: str
    model_used: str
    usage: dict[str, Any] = {}
    latency_ms: float
    fallback_used: bool = False
    error: str | None = None


# ── 内部工具 ──────────────────────────────────────────


def _headers() -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {_llm_api_key()}",
        "Content-Type": "application/json",
    }
    # OpenRouter 要求 Referer/Title；Novita 不需要
    if "openrouter.ai" in _llm_base_url():
        headers["HTTP-Referer"] = HTTP_REFERER
        headers["X-Title"] = APP_TITLE
    return headers


def _build_body(
    messages: list[dict],
    model: str,
    temperature: float = 0.85,
    max_tokens: int = 800,
) -> dict:
    return {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }


async def _call_once(
    messages: list[dict],
    model: str,
    timeout_s: float,
    trace_id: str,
) -> tuple[str, dict]:
    """
    单次调用 LLM 网关（Novita / OpenRouter 等 OpenAI 兼容端点）。
    返回 (content, usage_dict)。
    抛出 httpx.TimeoutException 或 RuntimeError（非 2xx）。
    """
    body = _build_body(messages, model)
    url = f"{_llm_base_url()}/chat/completions"

    logger.info(f"[{trace_id}] llm.call.start model={model} timeout={timeout_s}s")
    t0 = time.time()

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(url, json=body, headers=_headers())

    latency = (time.time() - t0) * 1000
    logger.info(f"[{trace_id}] llm.call.response model={model} status={resp.status_code} latency={latency:.0f}ms")

    if resp.status_code >= 500:
        raise RuntimeError(f"LLM upstream 5xx: {resp.status_code} {resp.text[:200]}")
    if resp.status_code >= 400:
        raise RuntimeError(f"LLM upstream 4xx: {resp.status_code} {resp.text[:200]}")

    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return content, usage


# ── 公开接口 ──────────────────────────────────────────


async def chat(
    messages: list[dict],
    trace_id: str,
    temperature: float = 0.85,
    max_tokens: int = 800,
    force_model: str | None = None,
) -> LLMResult:
    """
    主入口：发送消息列表，返回 LLMResult。
    自动降级：PRIMARY 超时或 5xx → FALLBACK。
    force_model 可跳过路由（A/B 实验 / 测试用）。
    """
    if not _llm_api_key():
        logger.error(f"[{trace_id}] NOVITA_API_KEY / OPENROUTER_API_KEY not configured")
        return LLMResult(
            content="[LLM unavailable: API key not configured]",
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
                content="[LLM error: forced model failed]",
                model_used=force_model,
                latency_ms=(time.time() - start_ts) * 1000,
                error=str(e),
            )

    # ── 主模型 ────────────────────────────────────────
    primary_err: str | None = None
    try:
        content, usage = await _call_once(messages, _primary_model(), PRIMARY_TIMEOUT_S, trace_id)
        return LLMResult(
            content=content,
            model_used=_primary_model(),
            usage=usage,
            latency_ms=(time.time() - start_ts) * 1000,
            fallback_used=False,
        )
    except httpx.TimeoutException as e:
        primary_err = f"timeout: {e}"
        logger.warning(f"[{trace_id}] llm.primary.timeout model={_primary_model()} → fallback")
    except RuntimeError as e:
        primary_err = str(e)
        if "5xx" in primary_err:
            logger.warning(f"[{trace_id}] llm.primary.5xx model={_primary_model()} → fallback")
        else:
            # 4xx（如余额不足）不降级，直接返回错误
            logger.error(f"[{trace_id}] llm.primary.4xx model={_primary_model()} err={primary_err}")
            return LLMResult(
                content="[LLM error: request rejected by API]",
                model_used=_primary_model(),
                latency_ms=(time.time() - start_ts) * 1000,
                error=primary_err,
            )
    except Exception as e:
        primary_err = str(e)
        logger.warning(f"[{trace_id}] llm.primary.error model={_primary_model()} err={e} → fallback")

    # ── 备用模型 ──────────────────────────────────────
    logger.info(f"[{trace_id}] llm.fallback.start model={_fallback_model()} primary_err={primary_err}")
    try:
        content, usage = await _call_once(messages, _fallback_model(), FALLBACK_TIMEOUT_S, trace_id)
        return LLMResult(
            content=content,
            model_used=_fallback_model(),
            usage=usage,
            latency_ms=(time.time() - start_ts) * 1000,
            fallback_used=True,
        )
    except Exception as e:
        fallback_err = str(e)
        logger.error(
            f"[{trace_id}] llm.fallback.error model={_fallback_model()} "
            f"primary_err={primary_err} fallback_err={fallback_err}"
        )
        return LLMResult(
            content="[服务暂时不可用，请稍后再试]",
            model_used=_fallback_model(),
            latency_ms=(time.time() - start_ts) * 1000,
            fallback_used=True,
            error=f"primary={primary_err}; fallback={fallback_err}",
        )
