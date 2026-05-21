"""LLM wrapper that only operates on matched script material (P3-11)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from loguru import logger

from services.llm import LLMResult, chat as llm_chat

ChatFn = Callable[..., Awaitable[LLMResult]]

NO_SCRIPT_FALLBACK = "I do not have an approved script for this moment yet."


@dataclass(frozen=True)
class ScriptMaterial:
    script_hit_id: str
    content: str
    category_key: str | None = None
    title: str | None = None


@dataclass(frozen=True)
class ScriptWrapResult:
    content: str
    called_llm: bool
    degraded: bool
    reason: str | None = None
    model_used: str | None = None


async def wrap_matched_script_with_llm(
    *,
    user_text: str,
    script: ScriptMaterial | None,
    trace_id: str,
    persona_prompt: str | None = None,
    chat_fn: ChatFn = llm_chat,
) -> ScriptWrapResult:
    """Humanize one approved script hit; do not call LLM when no script matched."""
    if script is None or not (script.content or "").strip() or not script.script_hit_id:
        logger.bind(
            component="script_llm_wrapper",
            trace_id=trace_id,
            result="degraded",
            reason="script_not_matched",
        ).warning("script_llm_wrapper.no_script")
        return ScriptWrapResult(
            content=NO_SCRIPT_FALLBACK,
            called_llm=False,
            degraded=True,
            reason="script_not_matched",
        )

    system = (
        "You are ERIS' reply polishing layer. Rewrite only the approved script "
        "material into a natural chat reply. Do not add new offers, prices, facts, "
        "promises, or safety advice beyond the approved script."
    )
    if persona_prompt:
        system += "\nPersona style:\n" + persona_prompt.strip()[:1200]
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                "User message:\n"
                f"{user_text[:1000]}\n\n"
                "Approved script material:\n"
                f"{script.content[:3000]}\n\n"
                "Return the final reply only."
            ),
        },
    ]

    result = await chat_fn(messages=messages, trace_id=trace_id, temperature=0.55, max_tokens=260)
    if result.error or not result.content.strip():
        return ScriptWrapResult(
            content=script.content,
            called_llm=True,
            degraded=True,
            reason=result.error or "empty_llm_output",
            model_used=result.model_used,
        )
    return ScriptWrapResult(
        content=result.content.strip(),
        called_llm=True,
        degraded=False,
        model_used=result.model_used,
    )


def script_material_from_hit(hit: Any) -> ScriptMaterial | None:
    if hit is None:
        return None
    script_hit_id = getattr(hit, "script_hit_id", None) or getattr(hit, "id", None)
    content = getattr(hit, "content", None)
    if isinstance(hit, dict):
        script_hit_id = hit.get("script_hit_id") or hit.get("id")
        content = hit.get("content")
    if not script_hit_id or not content:
        return None
    return ScriptMaterial(
        script_hit_id=str(script_hit_id),
        content=str(content),
        category_key=(str(getattr(hit, "category_key")) if getattr(hit, "category_key", None) else None),
        title=(str(getattr(hit, "title")) if getattr(hit, "title", None) else None),
    )
