"""V001-P0-5：入站内容安全双层（关键词 + OpenAI Moderation）与 ``safety_result`` 结构。

- **关键词层**：本地正则，零依赖；命中即拦截（``block_reason`` 以 ``keyword:`` 前缀）。
- **Moderation 层**：``POST https://api.openai.com/v1/moderations``，需 ``OPENAI_API_KEY``。
  若仅 ``self-harm*`` 类目为真，**不拦截**（交给 ``llm_orchestrator`` 危机短路）。
- 任一层 API 失败 / 未配置 key：不因此拦截（fail-open），在 ``safety_result.moderation`` 中记录原因。

返回体写入 ``messages.safety_result``（JSONB），字段稳定便于 Admin / 审计。
"""
from __future__ import annotations

import re
from typing import Any, Optional

import httpx
from loguru import logger

from core.config import settings

# 极端违法 / 平台零容忍类（保持短小；运营可后续迁配置表）
_KEYWORD_BLOCK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(child\s*porn|child\s*sexual|csam)\b", re.IGNORECASE | re.UNICODE),
    re.compile(r"\b(non-?consensual\s*intimate)\b", re.IGNORECASE | re.UNICODE),
)


def _keyword_hit(text: str) -> tuple[bool, str | None]:
    t = (text or "").strip()
    if not t:
        return False, None
    for i, pat in enumerate(_KEYWORD_BLOCK_PATTERNS):
        if pat.search(t):
            return True, f"keyword:pattern_{i}"
    return False, None


def _moderation_should_block(
    categories: dict[str, Any],
    category_scores: dict[str, Any],
    flagged: bool,
) -> tuple[bool, str | None]:
    """在 ``flagged`` 为真时细分：自伤类放行，由危机协议处理。"""
    if categories.get("sexual/minors"):
        return True, "moderation:sexual_minors"
    if categories.get("self-harm") or categories.get("self-harm/intent"):
        return False, None
    if categories.get("self-harm/instructions"):
        return False, None

    if not flagged:
        return False, None

    def _f(name: str) -> float:
        try:
            return float(category_scores.get(name) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    if _f("sexual") >= 0.9:
        return True, "moderation:sexual"
    if max(_f("hate"), _f("hate/threatening")) >= 0.9:
        return True, "moderation:hate"
    if _f("violence") >= 0.95:
        return True, "moderation:violence"
    return False, None


async def _openai_moderation(
    text: str,
    *,
    trace_id: str,
) -> dict[str, Any]:
    """返回 moderation API 单条 ``results[0]`` 子集；失败时返回 ``{"error": "..."}``。"""
    key = settings.OPENAI_API_KEY
    if not key or not (settings.CONTENT_SAFETY_MODERATION_ENABLED):
        return {"skipped": True, "reason": "moderation_disabled_or_no_api_key"}

    payload = {"input": (text or "")[:8000]}
    try:
        async with httpx.AsyncClient(
            timeout=float(settings.CONTENT_SAFETY_MODERATION_TIMEOUT_S or 12.0)
        ) as client:
            resp = await client.post(
                "https://api.openai.com/v1/moderations",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.status_code != 200:
                return {
                    "skipped": True,
                    "reason": f"http_{resp.status_code}",
                    "detail": (resp.text or "")[:500],
                }
            data = resp.json()
            results = data.get("results") or []
            if not results:
                return {"skipped": True, "reason": "empty_results"}
            r0 = results[0]
            return {
                "flagged": bool(r0.get("flagged")),
                "categories": r0.get("categories") or {},
                "category_scores": r0.get("category_scores") or {},
            }
    except Exception as exc:
        logger.bind(trace_id=trace_id, err=str(exc)).warning(
            "content_safety.moderation.request_failed"
        )
        return {"skipped": True, "reason": "request_error", "error": str(exc)[:300]}


async def evaluate_inbound_content_safety(
    text: str,
    *,
    trace_id: str,
) -> dict[str, Any]:
    """生成写入 ``messages.safety_result`` 的文档，并给出是否拦截入站处理。"""
    if not settings.CONTENT_SAFETY_ENABLED:
        return {
            "blocked": False,
            "block_reason": None,
            "keyword": {"skipped": True, "reason": "content_safety_disabled"},
            "moderation": {"skipped": True, "reason": "content_safety_disabled"},
        }

    kw_hit, kw_reason = _keyword_hit(text)
    keyword_layer: dict[str, Any] = {
        "hit": kw_hit,
        "reason": kw_reason,
    }

    if kw_hit:
        return {
            "blocked": True,
            "block_reason": kw_reason,
            "keyword": keyword_layer,
            "moderation": {"skipped": True, "reason": "keyword_already_blocked"},
        }

    mod: dict[str, Any] = await _openai_moderation(text, trace_id=trace_id)
    if mod.get("skipped"):
        return {
            "blocked": False,
            "block_reason": None,
            "keyword": keyword_layer,
            "moderation": mod,
        }

    cats = mod.get("categories") or {}
    scores = mod.get("category_scores") or {}
    flagged = bool(mod.get("flagged"))
    block, m_reason = _moderation_should_block(cats, scores, flagged)
    mod_out = {
        "flagged": flagged,
        "categories": {k: bool(v) for k, v in cats.items() if v},
        "category_scores": {
            k: round(float(v), 6)
            for k, v in scores.items()
            if isinstance(v, (int, float)) and float(v) >= 0.01
        },
    }
    if block:
        return {
            "blocked": True,
            "block_reason": m_reason,
            "keyword": keyword_layer,
            "moderation": mod_out,
        }

    return {
        "blocked": False,
        "block_reason": None,
        "keyword": keyword_layer,
        "moderation": mod_out,
    }
