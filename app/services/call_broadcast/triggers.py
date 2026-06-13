"""Inbound trigger: live video-call keywords defer to operator handoff (no auto-dial)."""

from __future__ import annotations

from loguru import logger

from core.config import settings
from services.call_broadcast.keywords import (
    is_video_call_request,
    matched_video_call_keyword,
)


async def maybe_enqueue_call_broadcast(
    *,
    user_id: str,
    external_user_id: str | None,
    conversation_id: str | None,
    chat_id: int,
    account_id: str | None,
    user_text: str | None,
    trace_id: str | None,
    telegram_access_hash: int | None = None,
) -> int:
    """Live-call keywords are handled by operator handoff; never auto-dial here."""
    if not getattr(settings, "CALL_BROADCAST_ENABLED", False):
        return 0
    if not is_video_call_request(user_text):
        return 0

    logger.bind(
        component="call_broadcast",
        trace_id=trace_id,
        user_id=user_id,
        chat_id=chat_id,
        matched_keyword=matched_video_call_keyword(user_text),
        video_intent="live_call",
    ).info("call_broadcast.keyword.routed_to_operator_handoff")
    return 0
