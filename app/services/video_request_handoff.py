"""Split live video-call intent vs prerecorded video-file intent.

Live-call text requests appear on /admin/video-broadcast as pending_operator jobs.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Mapping

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from services.call_broadcast.incoming_review_registry import register_pending_review
from services.call_broadcast.jobs import (
    create_keyword_live_video_review_job,
    resolve_inbound_call_context,
)
from services.call_broadcast.keywords import (
    is_video_call_request,
    matched_video_call_keyword,
)

VideoIntentKind = Literal["live_call", "prerecorded_file"]

# Retrospective praise is not a new video request.
_VIDEO_NEGATIVE_RE = re.compile(
    r"(昨天|上次|之前|刚才|那个|之前那个).{0,16}(视频|vid|clip|录像)|"
    r"(视频|vid|clip|录像).{0,10}(拍得|拍得真|不错|很好|好笑|很棒)",
    re.IGNORECASE | re.UNICODE,
)

_PRERECORDED_ZH_RE = re.compile(
    r"(发|给|来|看|有|要|能|可以|想|想要).{0,12}(视频|小视频|片子|录像)|"
    r"(视频|小视频|片子|录像).{0,6}(吗|嘛|么|呢)|"
    r"发个?视频",
    re.UNICODE,
)

_PRERECORDED_EN_RE = re.compile(
    r"\b(send|show|share|drop|give|upload|want|wanna|need|lemme|let\s+me)\b"
    r"(.{0,20}\b)?(your\s+)?(short\s+|dirty\s+|private\s+|bedroom\s+)?"
    r"(videos?|vids?|clips?|recordings?|tapes?)\b|"
    r"\b(videos?|vids?|clips?|recordings?|tapes?)\b.{0,16}\b(please|pls|me)\b",
    re.IGNORECASE,
)


def is_live_video_call_request(user_text: str | None) -> bool:
    return is_video_call_request(user_text)


def _matched_prerecorded_whitelist_keyword(user_text: str | None) -> str | None:
    from services.app_download_conversion import (
        ASSET_VIDEO_KEYWORDS,
        _keyword_matches,
        _normalize_keyword_text,
    )

    if is_live_video_call_request(user_text):
        return None
    normalized = _normalize_keyword_text(user_text)
    if not normalized:
        return None
    for keyword in ASSET_VIDEO_KEYWORDS:
        if _keyword_matches(normalized, keyword, asset_kind="video"):
            return keyword
    return None


def is_prerecorded_video_file_request(user_text: str | None) -> bool:
    text_value = str(user_text or "").strip()
    if not text_value:
        return False
    if is_live_video_call_request(text_value):
        return False
    if _VIDEO_NEGATIVE_RE.search(text_value):
        return False
    if _matched_prerecorded_whitelist_keyword(text_value):
        return True
    if _PRERECORDED_ZH_RE.search(text_value) or _PRERECORDED_EN_RE.search(text_value):
        return True
    return False


def classify_video_intent(user_text: str | None) -> VideoIntentKind | None:
    if is_live_video_call_request(user_text):
        return "live_call"
    if is_prerecorded_video_file_request(user_text):
        return "prerecorded_file"
    return None


def requires_operator_video_handoff(user_text: str | None) -> bool:
    return is_live_video_call_request(user_text)


def is_asset_video_file_request(user_text: str | None) -> bool:
    return is_prerecorded_video_file_request(user_text)


def has_video_request_intent(user_text: str | None) -> bool:
    return classify_video_intent(user_text) is not None


async def _match_prerecorded_video_template_keyword(
    db: AsyncSession,
    *,
    user_text: str,
    user_level: str,
    persona_slug: str | None,
    language: str,
) -> str | None:
    from services.app_download_conversion import (
        _asset_kind_from_title,
        _match_asset_keyword_triggers,
    )

    if is_live_video_call_request(user_text):
        return None
    matches = await _match_asset_keyword_triggers(
        db=db,
        user_text=user_text,
        user_level=user_level,
        persona_slug=persona_slug,
        language=language,
    )
    for hit, keyword in matches:
        if _asset_kind_from_title(str(hit.get("title") or "")) == "video":
            return keyword
    return None


async def resolve_live_video_call_intent(user_text: str | None) -> str | None:
    if not is_live_video_call_request(user_text):
        return None
    return matched_video_call_keyword(user_text) or "video_call"


async def resolve_prerecorded_video_file_intent(
    db: AsyncSession | None,
    user_text: str | None,
    *,
    user_level: str = "C",
    persona_slug: str | None = None,
    language: str = "en",
) -> str | None:
    text_value = str(user_text or "").strip()
    if not text_value or is_live_video_call_request(text_value):
        return None
    if _VIDEO_NEGATIVE_RE.search(text_value):
        return None
    whitelist = _matched_prerecorded_whitelist_keyword(text_value)
    if whitelist:
        return whitelist
    if _PRERECORDED_ZH_RE.search(text_value) or _PRERECORDED_EN_RE.search(text_value):
        return "pattern"
    if db is not None:
        template_keyword = await _match_prerecorded_video_template_keyword(
            db,
            user_text=text_value,
            user_level=user_level,
            persona_slug=persona_slug,
            language=language,
        )
        if template_keyword:
            return template_keyword
    return None


async def resolve_video_request_intent(
    db: AsyncSession | None,
    user_text: str | None,
    *,
    user_level: str = "C",
    persona_slug: str | None = None,
    language: str = "en",
) -> str | None:
    return await resolve_live_video_call_intent(user_text)


async def _pending_operator_job_exists(
    db: AsyncSession,
    *,
    chat_id: int,
    account_id: str,
) -> bool:
    row = (
        await db.execute(
            text(
                """
                SELECT 1
                FROM call_broadcast_jobs
                WHERE chat_id = :chat_id
                  AND account_id = CAST(:account_id AS uuid)
                  AND status = 'pending_operator'
                LIMIT 1
                """
            ),
            {"chat_id": int(chat_id), "account_id": account_id},
        )
    ).fetchone()
    return row is not None


async def maybe_queue_live_video_call_operator_review(
    db: AsyncSession,
    *,
    user_id: str,
    external_user_id: str | None,
    conversation_id: str,
    chat_id: int,
    account_id: str,
    user_text: str,
    trace_id: str | None = None,
    telegram_access_hash: int | None = None,
) -> str | None:
    """Queue pending_operator job for /admin/video-broadcast incoming reviews."""
    if not getattr(settings, "VIDEO_REQUEST_OPERATOR_HANDOFF_ENABLED", True):
        return None

    matched = await resolve_live_video_call_intent(user_text)
    if not matched:
        return None

    log = logger.bind(
        trace_id=trace_id,
        component="video_request_handoff",
        user_id=user_id,
        conversation_id=conversation_id,
        chat_id=chat_id,
        account_id=account_id,
        video_intent="live_call",
    )

    if await _pending_operator_job_exists(db, chat_id=chat_id, account_id=account_id):
        log.bind(matched_reason=matched).info("video_request_handoff.skip.pending_operator_exists")
        return None

    call_ctx = await resolve_inbound_call_context(db, int(chat_id))
    inbound_call_number = int(call_ctx["inbound_call_number"])
    completed_inbound_calls = int(call_ctx["completed_inbound_calls"])

    job_id = await create_keyword_live_video_review_job(
        db,
        user_id=user_id,
        external_user_id=external_user_id,
        conversation_id=conversation_id,
        chat_id=int(chat_id),
        account_id=account_id,
        trace_id=trace_id or "keyword-live-video",
        matched_keyword=matched,
        telegram_access_hash=telegram_access_hash,
        inbound_call_number=inbound_call_number,
        completed_inbound_calls=completed_inbound_calls,
    )
    if not job_id:
        log.warning("video_request_handoff.keyword_job_failed")
        return None

    ttl = int(getattr(settings, "CALL_BROADCAST_KEYWORD_REVIEW_TTL_SECONDS", 600))
    register_pending_review(
        job_id=job_id,
        account_id=account_id,
        chat_id=int(chat_id),
        access_hash=telegram_access_hash,
        trace_id=trace_id or "keyword-live-video",
        inbound_call_number=inbound_call_number,
        ttl_seconds=ttl,
    )
    await db.commit()

    log.bind(job_id=job_id, matched_reason=matched).info(
        "video_request_handoff.keyword_review_queued"
    )
    return job_id


# Backward-compatible alias used by older call sites.
async def maybe_create_video_request_handoff(
    db: AsyncSession,
    *,
    user_id: str,
    conversation_id: str,
    user_text: str,
    profile_row: Mapping[str, Any] | None = None,
    trace_id: str | None = None,
    user_level: str | None = None,
    persona_slug: str | None = None,
    language: str | None = None,
    chat_id: int | None = None,
    account_id: str | None = None,
    external_user_id: str | None = None,
    telegram_access_hash: int | None = None,
) -> str | None:
    if chat_id is None or not account_id:
        return None
    return await maybe_queue_live_video_call_operator_review(
        db,
        user_id=user_id,
        external_user_id=external_user_id,
        conversation_id=conversation_id,
        chat_id=int(chat_id),
        account_id=str(account_id),
        user_text=user_text,
        trace_id=trace_id,
        telegram_access_hash=telegram_access_hash,
    )
