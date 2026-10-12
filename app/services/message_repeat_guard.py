"""Block sending the same assistant outbound text to a user within a cooldown window."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from loguru import logger
from sqlalchemy import text

from core.config import settings
from services.link_cooldown import _BTW_NUDGE_RE, _OPEN_APP_CTA_RE, _TRACKING_URL_RE, _USE_CODE_RE

_CODE_SUFFIX_RE = re.compile(r"\s*\((?:Use|Code):\s*c5a8we\)", re.IGNORECASE)
_MIN_DUPLICATE_SEGMENT_CHARS = 20


def outbound_message_repeat_cooldown_hours() -> int:
    return max(0, int(getattr(settings, "OUTBOUND_MESSAGE_REPEAT_COOLDOWN_HOURS", 2)))


def canonical_outbound_content(content: str | None) -> str:
    """Normalize outbound text so tracking-link variants compare equal."""
    value = str(content or "").strip()
    if not value:
        return ""
    value = _BTW_NUDGE_RE.sub("", value)
    value = _OPEN_APP_CTA_RE.sub("", value)
    value = _TRACKING_URL_RE.sub("", value)
    value = _USE_CODE_RE.sub("", value)
    value = _CODE_SUFFIX_RE.sub("", value)
    value = re.sub(r"https?://[^\s<>\]\"']+", "", value, flags=re.IGNORECASE)
    return " ".join(value.split()).casefold()


def outbound_content_segments(content: str | None) -> list[str]:
    """Split outbound text into logical segments (paragraphs / nurture boilerplate blocks)."""
    value = str(content or "").strip()
    if not value:
        return []
    parts = [part.strip() for part in re.split(r"\n\s*\n+", value) if part.strip()]
    return parts or [value]


def duplicate_check_segments(content: str | None) -> list[str]:
    """Return normalized segment fingerprints used for repeat detection."""
    segments: list[str] = []
    seen: set[str] = set()
    full = canonical_outbound_content(content)
    if full:
        segments.append(full)
        seen.add(full)
    for part in outbound_content_segments(content):
        canonical = canonical_outbound_content(part)
        if not canonical or len(canonical) < _MIN_DUPLICATE_SEGMENT_CHARS:
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        segments.append(canonical)
    return segments


def _segment_dedupe_key(user_id: str, segment: str) -> str:
    digest = hashlib.sha256(segment.encode("utf-8")).hexdigest()[:32]
    return f"outbound_dup:{user_id}:{digest}"


def _content_matches_prior_segments(target_segments: list[str], prior_content: str) -> bool:
    prior_segments = duplicate_check_segments(prior_content)
    if not prior_segments:
        return False
    prior_set = set(prior_segments)
    return any(segment in prior_set for segment in target_segments)


async def _redis_has_recent_duplicate(
    redis: Any,
    *,
    user_id: str,
    content: str,
) -> bool:
    if redis is None:
        return False
    for segment in duplicate_check_segments(content):
        if await redis.get(_segment_dedupe_key(user_id, segment)):
            return True
    return False


async def _redis_claim_segments(
    redis: Any,
    *,
    user_id: str,
    content: str,
) -> bool:
    if redis is None:
        return True
    ttl_seconds = outbound_message_repeat_cooldown_hours() * 3600
    if ttl_seconds <= 0:
        return True
    for segment in duplicate_check_segments(content):
        key = _segment_dedupe_key(user_id, segment)
        claimed = await redis.set(key, "1", nx=True, ex=ttl_seconds)
        if not claimed:
            return False
    return True


async def user_recently_received_same_content(
    db: Any,
    *,
    user_id: str,
    content: str,
    cooldown_hours: int | None = None,
) -> bool:
    """Return True when the user already received equivalent assistant content recently."""
    hours = outbound_message_repeat_cooldown_hours() if cooldown_hours is None else max(0, cooldown_hours)
    target_segments = duplicate_check_segments(content)
    if hours <= 0 or not target_segments or db is None:
        return False

    result = await db.execute(
        text(
            """
            SELECT DISTINCT m.content
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE c.user_id = CAST(:user_id AS uuid)
              AND m.sender_type = 'assistant'
              AND m.created_at >= NOW() - make_interval(hours => :hours)
              AND COALESCE(BTRIM(m.content), '') <> ''
            """
        ),
        {"user_id": user_id, "hours": hours},
    )
    for row in result.fetchall():
        data = row._mapping if hasattr(row, "_mapping") else row
        prior_content = str(data.get("content") or "")
        if _content_matches_prior_segments(target_segments, prior_content):
            return True
    return False


async def should_skip_duplicate_outbound(
    db: Any,
    *,
    user_id: str,
    content: str,
    trace_id: str | None = None,
    source: str | None = None,
    redis: Any = None,
) -> bool:
    """Log and return True when outbound content must be suppressed as a repeat."""
    target_segments = duplicate_check_segments(content)
    if not target_segments:
        return False

    first_reply = False
    if db is not None:
        first_reply = not bool(
            (await db.execute(
                text("""
                    SELECT EXISTS (
                        SELECT 1 FROM messages m
                        JOIN conversations c ON c.id = m.conversation_id
                        WHERE c.user_id = CAST(:user_id AS uuid)
                          AND m.sender_type = 'assistant'
                    )
                """),
                {"user_id": user_id},
            )).scalar()
        )
    if first_reply:
        if redis is not None:
            claimed = await redis.set(
                f"outbound_first_reply:{user_id}", "1", nx=True, ex=120
            )
            if not claimed:
                logger.bind(
                    component="message_repeat_guard", trace_id=trace_id,
                    user_id=user_id, source=source or "unknown",
                ).info("message_repeat_guard.first_reply_inflight_skip")
                return True
        logger.bind(
            component="message_repeat_guard", trace_id=trace_id,
            user_id=user_id, source=source or "unknown",
        ).info("message_repeat_guard.first_reply_allowed")
        return False
    if await _redis_has_recent_duplicate(redis, user_id=user_id, content=content):
        logger.bind(
            component="message_repeat_guard",
            trace_id=trace_id,
            user_id=user_id,
            source=source or "unknown",
            cooldown_hours=outbound_message_repeat_cooldown_hours(),
            match_kind="redis",
        ).info("message_repeat_guard.duplicate_skip")
        return True

    if await user_recently_received_same_content(db, user_id=user_id, content=content):
        logger.bind(
            component="message_repeat_guard",
            trace_id=trace_id,
            user_id=user_id,
            source=source or "unknown",
            cooldown_hours=outbound_message_repeat_cooldown_hours(),
            match_kind="db",
        ).info("message_repeat_guard.duplicate_skip")
        return True

    if not await _redis_claim_segments(redis, user_id=user_id, content=content):
        logger.bind(
            component="message_repeat_guard",
            trace_id=trace_id,
            user_id=user_id,
            source=source or "unknown",
            cooldown_hours=outbound_message_repeat_cooldown_hours(),
            match_kind="redis_claim",
        ).info("message_repeat_guard.duplicate_skip")
        return True

    return False
