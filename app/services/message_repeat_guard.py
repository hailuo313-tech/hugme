"""Block sending the same assistant outbound text to a user within a cooldown window."""

from __future__ import annotations

import re
from typing import Any

from loguru import logger
from sqlalchemy import text

from core.config import settings
from services.link_cooldown import _BTW_NUDGE_RE, _OPEN_APP_CTA_RE, _TRACKING_URL_RE, _USE_CODE_RE

_CODE_SUFFIX_RE = re.compile(r"\s*\((?:Use|Code):\s*c5a8we\)", re.IGNORECASE)


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


async def user_recently_received_same_content(
    db: Any,
    *,
    user_id: str,
    content: str,
    cooldown_hours: int | None = None,
) -> bool:
    """Return True when the user already received equivalent assistant content recently."""
    hours = outbound_message_repeat_cooldown_hours() if cooldown_hours is None else max(0, cooldown_hours)
    target = canonical_outbound_content(content)
    if hours <= 0 or not target or db is None:
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
        prior = canonical_outbound_content(str(data.get("content") or ""))
        if prior and prior == target:
            return True
    return False


async def should_skip_duplicate_outbound(
    db: Any,
    *,
    user_id: str,
    content: str,
    trace_id: str | None = None,
    source: str | None = None,
) -> bool:
    """Log and return True when outbound content must be suppressed as a repeat."""
    if not await user_recently_received_same_content(db, user_id=user_id, content=content):
        return False
    logger.bind(
        component="message_repeat_guard",
        trace_id=trace_id,
        user_id=user_id,
        source=source or "unknown",
        cooldown_hours=outbound_message_repeat_cooldown_hours(),
    ).info("message_repeat_guard.duplicate_skip")
    return True
