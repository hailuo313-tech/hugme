"""V001-P0-5：入站内容安全双层（关键词 + Novita AI LLM）与 ``safety_result`` 结构。

- **关键词层**：本地正则，零依赖；命中即拦截（``block_reason`` 以 ``keyword:`` 前缀）。
- **LLM 层**：使用 Novita AI LLM 判断内容安全性，需 ``NOVITA_API_KEY``。
  若仅 ``self-harm*`` 类别为真，**不拦截**（交给 ``llm_orchestrator`` 危机短路）。
- 任一层 API 失败 / 未配置 key：不因此拦截（fail-open），在 ``safety_result.moderation`` 中记录原因。

返回体写入 ``messages.safety_result``（JSONB），字段稳定便于 Admin / 审计。
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

import httpx
from loguru import logger

from core.config import settings

# 极端违法 / 平台零容忍类（保持短小；运营可后续迁配置表）
_KEYWORD_BLOCK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(child\s*porn|child\s*sexual|csam)\b", re.IGNORECASE | re.UNICODE),
    re.compile(r"\b(non-?consensual\s*intimate)\b", re.IGNORECASE | re.UNICODE),
    re.compile(
        r"(ignore\s+(all\s+)?(previous|above)\s+instructions|jailbreak|DAN\s+mode|"
        r"你现在是\s*GPT|忽略以上规则|无视.*规则)",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        r"\b(how\s+to\s+make\s+(a\s+)?bomb|make\s+meth|武器制造|炸弹制作)\b",
        re.IGNORECASE | re.UNICODE,
    ),
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
    flagged: bool,
    skip_sexual_block: bool = False,
) -> tuple[bool, str | None]:
    """在 ``flagged`` 为真时细分：自伤类放行，由危机协议处理。

    Args:
        categories: Novita AI LLM 返回的类别
        flagged: 是否被标记
        skip_sexual_block: 是否跳过sexual内容拦截（用于premium_nsfw_companion模式）
    """
    if categories.get("sexual/minors"):
        return True, "moderation:sexual_minors"
    if categories.get("self-harm"):
        return False, None

    if not flagged:
        return False, None

    # 在 premium_nsfw_companion 模式下跳过 sexual 拦截
    if not skip_sexual_block and categories.get("sexual"):
        return True, "moderation:sexual"
    if categories.get("hate"):
        return True, "moderation:hate"
    if categories.get("violence"):
        return True, "moderation:violence"
    return False, None


async def _novita_llm_moderation(
    text: str,
    *,
    trace_id: str,
) -> dict[str, Any]:
    """使用 Novita AI LLM 判断内容安全性。失败时返回 ``{"error": "..."}``。"""
    if not settings.NOVITA_API_KEY or not (settings.CONTENT_SAFETY_MODERATION_ENABLED):
        return {"skipped": True, "reason": "moderation_disabled_or_no_api_key"}

    # 使用 LLM 判断内容安全性
    prompt = f"""请判断以下文本内容是否包含有害内容。返回 JSON 格式：

{{
  "flagged": true/false,
  "categories": {{
    "sexual": true/false,
    "sexual/minors": true/false,
    "hate": true/false,
    "violence": true/false,
    "self-harm": true/false
  }}
}}

文本内容：{text[:1000]}

只返回 JSON，不要有其他内容。"""

    try:
        async with httpx.AsyncClient(
            timeout=float(settings.CONTENT_SAFETY_MODERATION_TIMEOUT_S or 12.0)
        ) as client:
            resp = await client.post(
                f"{settings.NOVITA_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.NOVITA_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.NOVITA_CHAT_MODEL,
                    "messages": [
                        {"role": "system", "content": "你是一个内容安全审查助手，负责判断文本是否包含有害内容。"},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 200,
                },
            )
            if resp.status_code != 200:
                return {
                    "skipped": True,
                    "reason": f"http_{resp.status_code}",
                    "detail": (resp.text or "")[:500],
                }
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()

            # 解析 LLM 返回的 JSON
            try:
                result = json.loads(content)
                return {
                    "flagged": bool(result.get("flagged", False)),
                    "categories": result.get("categories", {}),
                }
            except json.JSONDecodeError:
                logger.bind(trace_id=trace_id, content=content).warning(
                    "content_safety.llm_moderation.invalid_json"
                )
                return {"skipped": True, "reason": "invalid_json_response"}
    except Exception as exc:
        logger.bind(trace_id=trace_id, err=str(exc)).warning(
            "content_safety.llm_moderation.request_failed"
        )
        return {"skipped": True, "reason": "request_error", "error": str(exc)[:300]}


async def evaluate_inbound_content_safety(
    text: str,
    *,
    trace_id: str,
    skip_sexual_block: bool = False,
) -> dict[str, Any]:
    """生成写入 ``messages.safety_result`` 的文档，并给出是否拦截入站处理。
    
    Args:
        text: 要检查的文本
        trace_id: 追踪ID
        skip_sexual_block: 是否跳过sexual内容拦截（用于premium_nsfw_companion模式）
    """
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

    mod: dict[str, Any] = await _novita_llm_moderation(text, trace_id=trace_id)
    if mod.get("skipped"):
        return {
            "blocked": False,
            "block_reason": None,
            "keyword": keyword_layer,
            "moderation": mod,
        }

    cats = mod.get("categories") or {}
    flagged = bool(mod.get("flagged"))
    block, m_reason = _moderation_should_block(cats, flagged, skip_sexual_block)
    mod_out = {
        "flagged": flagged,
        "categories": {k: bool(v) for k, v in cats.items() if v},
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
