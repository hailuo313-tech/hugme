"""P2-04: extract user age with confidence before writing profile data."""
from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal

AGE_WRITE_CONFIDENCE_THRESHOLD = 0.75
MIN_EXTRACTED_AGE = 13
MAX_EXTRACTED_AGE = 120
AGE_PROFILE_KEY = "ai_extracted_age"

ChatFn = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class AgeExtractionResult:
    age: int | None
    confidence: float
    source: str = "llm"
    reason: str = ""
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class AgeWriteDecision:
    should_write: bool
    reason: str
    age: int | None
    confidence: float


def decide_age_profile_write(
    result: AgeExtractionResult,
    *,
    threshold: float = AGE_WRITE_CONFIDENCE_THRESHOLD,
) -> AgeWriteDecision:
    """Return whether an extracted age is safe enough to persist."""
    if result.age is None:
        return AgeWriteDecision(False, "missing_age", None, result.confidence)
    if not MIN_EXTRACTED_AGE <= result.age <= MAX_EXTRACTED_AGE:
        return AgeWriteDecision(False, "age_out_of_range", result.age, result.confidence)
    if result.confidence < threshold:
        return AgeWriteDecision(False, "low_confidence", result.age, result.confidence)
    return AgeWriteDecision(True, "confidence_met", result.age, result.confidence)


def parse_age_extraction_payload(payload: str | dict[str, Any]) -> AgeExtractionResult:
    """Parse the JSON-only LLM response used by the age extractor."""
    data = payload if isinstance(payload, dict) else _loads_json_object(payload)
    age = _as_optional_int(data.get("age"))
    confidence = _clamp_confidence(data.get("confidence"))
    reason = str(data.get("reason") or "").strip()
    source = str(data.get("source") or "llm").strip() or "llm"

    if age is not None and not MIN_EXTRACTED_AGE <= age <= MAX_EXTRACTED_AGE:
        return AgeExtractionResult(
            age=None,
            confidence=confidence,
            source=source,
            reason=reason or "age_out_of_range",
            raw=data,
        )

    return AgeExtractionResult(
        age=age,
        confidence=confidence,
        source=source,
        reason=reason,
        raw=data,
    )


async def extract_age_with_llm(
    *,
    content: str,
    trace_id: str,
    chat_fn: ChatFn | None = None,
) -> AgeExtractionResult:
    """Ask the LLM for a structured age signal and normalize the result."""
    if not content or not content.strip():
        return AgeExtractionResult(age=None, confidence=0.0, reason="empty_content")

    llm_chat = chat_fn or await _default_chat_fn()
    result = await llm_chat(
        messages=_build_age_extraction_messages(content),
        trace_id=trace_id,
        temperature=0.0,
        max_tokens=120,
    )
    if getattr(result, "error", None):
        return AgeExtractionResult(age=None, confidence=0.0, reason="llm_error")

    return parse_age_extraction_payload(str(getattr(result, "content", "") or ""))


async def maybe_extract_and_write_age(
    *,
    user_id: str,
    content: str,
    trace_id: str,
    db: AsyncSession | None = None,
    chat_fn: ChatFn | None = None,
    threshold: float = AGE_WRITE_CONFIDENCE_THRESHOLD,
) -> AgeWriteDecision:
    """Extract age and persist only high-confidence values to user_profiles."""
    log = logger.bind(component="age_extraction", trace_id=trace_id, user_id=user_id)
    try:
        result = await extract_age_with_llm(
            content=content,
            trace_id=trace_id,
            chat_fn=chat_fn,
        )
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("age.extract.failed")
        return AgeWriteDecision(False, "extract_failed", None, 0.0)

    decision = decide_age_profile_write(result, threshold=threshold)
    if not decision.should_write:
        log.bind(
            age=decision.age,
            confidence=decision.confidence,
            reason=decision.reason,
        ).info("age.extract.skip_write")
        return decision

    payload = {
        "age": decision.age,
        "confidence": decision.confidence,
        "source": result.source,
        "reason": result.reason,
        "updated_at": datetime.now(UTC).isoformat(),
    }

    try:
        if db is not None:
            await _write_age_profile(db, user_id=user_id, payload=payload)
            await db.commit()
        else:
            async with AsyncSessionLocal() as own_db:
                await _write_age_profile(own_db, user_id=user_id, payload=payload)
                await own_db.commit()
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("age.write.failed")
        return AgeWriteDecision(False, "write_failed", decision.age, decision.confidence)

    log.bind(age=decision.age, confidence=decision.confidence).info("age.write.persisted")
    return decision


async def _write_age_profile(
    db: AsyncSession,
    *,
    user_id: str,
    payload: dict[str, Any],
) -> None:
    await db.execute(
        text(
            """
            UPDATE user_profiles
            SET preferences = jsonb_set(
                    COALESCE(preferences, '{}'::jsonb),
                    CAST(:path AS text[]),
                    CAST(:payload AS jsonb),
                    true
                ),
                updated_at = NOW()
            WHERE user_id = CAST(:uid AS uuid)
            """
        ),
        {
            "uid": user_id,
            "path": "{" + AGE_PROFILE_KEY + "}",
            "payload": json.dumps(payload, ensure_ascii=False),
        },
    )


def _build_age_extraction_messages(content: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Extract the user's own age from the message. Return only JSON with "
                'keys: "age" (integer or null), "confidence" (0..1), "reason" '
                'and "source". Use confidence below 0.75 for ambiguous, joking, '
                "hypothetical, third-person, or inferred ages."
            ),
        },
        {"role": "user", "content": content[:2000]},
    ]


async def _default_chat_fn() -> ChatFn:
    from services.llm import chat

    return chat


def _loads_json_object(raw: str) -> dict[str, Any]:
    text_value = raw.strip()
    if not text_value:
        return {}
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text_value, re.S)
    if fenced:
        text_value = fenced.group(1)
    elif "{" in text_value and "}" in text_value:
        text_value = text_value[text_value.find("{") : text_value.rfind("}") + 1]
    try:
        data = json.loads(text_value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _as_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, confidence))
