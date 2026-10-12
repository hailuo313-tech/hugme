"""OpenAI-compatible LLM client with per-purpose Novita/OpenRouter routing."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from loguru import logger
from pydantic import BaseModel

from core.config import settings


PRIMARY_TIMEOUT_S = 25.0
FALLBACK_TIMEOUT_S = 20.0

HTTP_REFERER = "https://hugme2.com"
APP_TITLE = "ERIS Emotional Companion"
DEFAULT_FALLBACK_REPLY = "现在有点忙，稍后再聊好吗？"

LLMPurpose = Literal["chat", "aux"]


class LLMResult(BaseModel):
    content: str
    model_used: str
    usage: dict[str, Any] = {}
    latency_ms: float
    fallback_used: bool = False
    error: str | None = None


@dataclass(frozen=True)
class LLMProvider:
    name: str
    base_url: str
    api_key: str | None
    model: str


def _clean_base_url(base_url: str) -> str:
    return (base_url or "").rstrip("/")


def _provider_for(name: str, *, model: str | None = None) -> LLMProvider:
    provider = (name or "openrouter").strip().lower()
    if provider == "novita":
        return LLMProvider(
            name="novita",
            base_url=_clean_base_url(settings.LLM_API_BASE_URL),
            api_key=settings.NOVITA_API_KEY,
            model=model or settings.LLM_PRIMARY_MODEL,
        )
    return LLMProvider(
        name="openrouter",
        base_url=_clean_base_url(settings.OPENROUTER_BASE_URL),
        api_key=settings.OPENROUTER_API_KEY,
        model=model or settings.LLM_FALLBACK_MODEL,
    )


def _resolve_provider_name(
    *,
    purpose: LLMPurpose | None = None,
    provider: str | None = None,
) -> str:
    if provider:
        return provider.strip().lower()
    if purpose == "chat":
        return (settings.LLM_CHAT_PROVIDER or settings.LLM_PROVIDER or "openrouter").strip().lower()
    if purpose == "aux":
        return (settings.LLM_AUX_PROVIDER or "openrouter").strip().lower()
    return (settings.LLM_PROVIDER or "openrouter").strip().lower()


def _resolve_model(provider_name: str, *, purpose: LLMPurpose | None, force_model: str | None) -> str:
    if force_model:
        return force_model
    if purpose == "chat" and (settings.LLM_CHAT_MODEL or "").strip():
        return settings.LLM_CHAT_MODEL.strip()
    if purpose == "aux" and (settings.LLM_AUX_MODEL or "").strip():
        return settings.LLM_AUX_MODEL.strip()
    if provider_name == "novita":
        return settings.LLM_PRIMARY_MODEL
    return settings.LLM_FALLBACK_MODEL


def _primary_provider(
    *,
    purpose: LLMPurpose | None = None,
    provider: str | None = None,
    force_model: str | None = None,
) -> LLMProvider:
    provider_name = _resolve_provider_name(purpose=purpose, provider=provider)
    model = _resolve_model(provider_name, purpose=purpose, force_model=force_model)
    return _provider_for(provider_name, model=model)


def _fallback_provider(primary: LLMProvider) -> LLMProvider | None:
    if primary.name == "novita" and settings.OPENROUTER_API_KEY:
        model = settings.LLM_AUX_MODEL or settings.LLM_FALLBACK_MODEL
        return _provider_for("openrouter", model=model)
    if primary.name != "novita" and settings.NOVITA_API_KEY:
        model = settings.LLM_CHAT_MODEL or settings.LLM_PRIMARY_MODEL
        return _provider_for("novita", model=model)
    return None


def _headers(provider: LLMProvider) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {provider.api_key}",
        "HTTP-Referer": HTTP_REFERER,
        "X-Title": APP_TITLE,
        "Content-Type": "application/json",
    }


def _build_body(
    messages: list[dict],
    model: str,
    temperature: float = 0.85,
    max_tokens: int = 800,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }


async def _call_once(
    messages: list[dict],
    provider: LLMProvider,
    timeout_s: float,
    trace_id: str,
    *,
    temperature: float,
    max_tokens: int,
) -> tuple[str, dict[str, Any]]:
    if not provider.api_key:
        raise RuntimeError(f"{provider.name.upper()}_API_KEY_MISSING")
    if not provider.base_url:
        raise RuntimeError(f"{provider.name.upper()}_BASE_URL_MISSING")

    body = _build_body(messages, provider.model, temperature=temperature, max_tokens=max_tokens)
    url = f"{provider.base_url}/chat/completions"

    logger.bind(provider=provider.name, model=provider.model).info(f"[{trace_id}] llm.call.start")
    t0 = time.time()

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(url, json=body, headers=_headers(provider))

    latency = (time.time() - t0) * 1000
    logger.bind(provider=provider.name, model=provider.model, status_code=resp.status_code, latency_ms=latency).info(
        f"[{trace_id}] llm.call.response"
    )

    if resp.status_code >= 500:
        raise RuntimeError(f"{provider.name} 5xx: {resp.status_code} {resp.text[:200]}")
    if resp.status_code >= 400:
        raise RuntimeError(f"{provider.name} 4xx: {resp.status_code} {resp.text[:200]}")

    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return content, usage


async def chat(
    messages: list[dict],
    trace_id: str,
    temperature: float = 0.85,
    max_tokens: int = 800,
    force_model: str | None = None,
    purpose: LLMPurpose | None = None,
    provider: str | None = None,
) -> LLMResult:
    """Send chat messages to the configured OpenAI-compatible provider.

    purpose:
      - ``chat``: user replies + operator AI assist drafts (Novita by default)
      - ``aux``: translation / memory scoring / age extraction (OpenRouter by default)
      - ``None``: legacy ``LLM_PROVIDER`` routing (e.g. /api/v1/llm/chat)
    """
    start_ts = time.time()
    primary = _primary_provider(purpose=purpose, provider=provider, force_model=force_model)
    allow_fallback = purpose in (None, "chat", "aux")

    try:
        content, usage = await _call_once(
            messages,
            primary,
            PRIMARY_TIMEOUT_S,
            trace_id,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return LLMResult(
            content=content,
            model_used=f"{primary.name}:{primary.model}",
            usage=usage,
            latency_ms=(time.time() - start_ts) * 1000,
            fallback_used=False,
        )
    except httpx.TimeoutException as exc:
        primary_err = f"timeout: {exc}"
        logger.bind(provider=primary.name, model=primary.model).warning(f"[{trace_id}] llm.primary.timeout")
    except RuntimeError as exc:
        primary_err = str(exc)
        logger.bind(provider=primary.name, model=primary.model).warning(f"[{trace_id}] llm.primary.error")
    except Exception as exc:
        primary_err = str(exc)
        logger.bind(provider=primary.name, model=primary.model, error_type=type(exc).__name__).warning(
            f"[{trace_id}] llm.primary.error"
        )

    fallback = _fallback_provider(primary) if allow_fallback and not force_model else None
    if fallback is None:
        logger.error(f"[{trace_id}] llm.no_fallback primary_err={primary_err}")
        return LLMResult(
            content=DEFAULT_FALLBACK_REPLY,
            model_used=f"{primary.name}:{primary.model}",
            latency_ms=(time.time() - start_ts) * 1000,
            error=primary_err,
        )

    try:
        content, usage = await _call_once(
            messages,
            fallback,
            FALLBACK_TIMEOUT_S,
            trace_id,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return LLMResult(
            content=content,
            model_used=f"{fallback.name}:{fallback.model}",
            usage=usage,
            latency_ms=(time.time() - start_ts) * 1000,
            fallback_used=True,
        )
    except Exception as exc:
        fallback_err = str(exc)
        logger.error(
            f"[{trace_id}] llm.fallback.error primary_err={primary_err} fallback_err={fallback_err}"
        )
        return LLMResult(
            content=DEFAULT_FALLBACK_REPLY,
            model_used=f"{fallback.name}:{fallback.model}",
            latency_ms=(time.time() - start_ts) * 1000,
            fallback_used=True,
            error=f"primary={primary_err}; fallback={fallback_err}",
        )
