"""Per-conversation outbound link cooldown (hard cap on link frequency)."""

from __future__ import annotations

import re

from sqlalchemy import text

from core.config import settings

URL_RE = re.compile(r"https?://[^\s<>\]\"']+")
_TRACKING_URL_RE = re.compile(r"https?://[^\s<>\]\"']+/r/[A-Za-z0-9]+", re.IGNORECASE)
_BTW_NUDGE_RE = re.compile(
    r"\n*\s*Btw, my TG is lagging crazy right now[^\n]*(?:\n[^\n]*)*",
    re.IGNORECASE,
)
_OPEN_APP_CTA_RE = re.compile(
    r"\n*\s*OPEN APP LINK - TAP HERE[^\n]*(?:\n[^\n]*)*",
    re.IGNORECASE,
)
_USE_CODE_RE = re.compile(r"\s*\(Use code: c5a8we\)", re.IGNORECASE)


def link_cooldown_minutes() -> int:
    return max(1, int(settings.APP_DOWNLOAD_LINK_COOLDOWN_MINUTES))


def is_within_link_cooldown(minutes_since_last_link: float | None) -> bool:
    if minutes_since_last_link is None:
        return False
    return minutes_since_last_link < float(link_cooldown_minutes())


async def minutes_since_last_assistant_link(
    db: object,
    *,
    conversation_id: str,
) -> float | None:
    """Minutes since the last assistant message that contained an http(s) link."""
    row = (
        await db.execute(  # type: ignore[union-attr]
            text(
                """
                SELECT EXTRACT(EPOCH FROM (NOW() - MAX(created_at))) / 60.0 AS minutes
                FROM messages
                WHERE conversation_id = CAST(:conversation_id AS uuid)
                  AND sender_type = 'assistant'
                  AND content ~* 'https?://'
                """
            ),
            {"conversation_id": conversation_id},
        )
    ).fetchone()
    if row is None:
        return None
    data = row._mapping if hasattr(row, "_mapping") else row
    minutes = data.get("minutes")
    if minutes is None:
        return None
    return float(minutes)


async def is_conversation_link_cooldown_active(
    db: object | None,
    *,
    conversation_id: str,
) -> bool:
    if db is None:
        return False
    minutes = await minutes_since_last_assistant_link(
        db,
        conversation_id=conversation_id,
    )
    return is_within_link_cooldown(minutes)


def reply_already_has_link_material(text_value: str) -> bool:
    """True when outbound text already carries a tracking/app link or nudge block."""
    if not text_value:
        return False
    if _BTW_NUDGE_RE.search(text_value):
        return True
    if _TRACKING_URL_RE.search(text_value):
        return True
    return bool(URL_RE.search(text_value))


def strip_links_from_reply(text_value: str) -> str:
    """Remove URLs and known download nudge blocks from an outbound reply."""
    if not text_value:
        return text_value
    cleaned = _BTW_NUDGE_RE.sub("", text_value)
    cleaned = _OPEN_APP_CTA_RE.sub("", cleaned)
    cleaned = URL_RE.sub("", cleaned)
    cleaned = _USE_CODE_RE.sub("", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
