from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from services.app_download_platforms import resolve_app_download_url
from services.level_engine import country_tier
from services.link_attribution import wrap_text_links_with_tracking
from services.profile_intake import age_from_preferences, normalize_country_code
from services.script_template_retriever import ScriptTemplateQuery, search_script_templates


APP_DOWNLOAD_NURTURE_DELIVERY_MODE = "app_download_nurture"
APP_DOWNLOAD_MESSAGE_TYPE = "app_download_followup"

TRIGGER_FIRST_IDLE = "first_message_idle_3m"
TRIGGER_WARM_NO_CLICK = "warm_chat_no_click"
TRIGGER_CLICK_NO_DOWNLOAD = "clicked_not_downloaded_10m"
TRIGGER_SILENT_30M = "silent_30m"
TRIGGER_SILENT_24H = "silent_24h"

_CTA_TRIGGERS = {
    TRIGGER_WARM_NO_CLICK,
    TRIGGER_CLICK_NO_DOWNLOAD,
    TRIGGER_SILENT_30M,
    TRIGGER_SILENT_24H,
}

# Only active rows block requeue; failed rows may be retried after a fix.
_ACTIVE_NURTURE_STATUSES = ("pending", "sending", "sent")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _row_dict(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    if isinstance(row, dict):
        return row
    return None


async def schedule_download_followups_after_reply(
    db: AsyncSession,
    *,
    user_id: str,
    external_user_id: str,
    conversation_id: str,
    chat_id: int | None,
    assistant_message_id: str,
    trace_id: str | None,
    account_id: str | None = None,
) -> int:
    """Queue business-specific App download follow-ups after a normal reply.

    Each queued row carries a stale guard. If the user replies after the assistant
    message, auto_delivery will skip the queued follow-up instead of sending a
    disconnected message.
    """
    if not settings.APP_DOWNLOAD_NURTURE_ENABLED or not chat_id:
        return 0

    sender_account_id = account_id or await resolve_nurture_sender_account_id(
        db,
        conversation_id=conversation_id,
    )

    destination_url = await resolve_app_download_url(db)
    if not destination_url:
        return 0

    state = await _load_conversation_state(db, user_id=user_id, conversation_id=conversation_id)
    if not state:
        return 0

    queued = 0
    last_assistant_at = state.get("last_assistant_at") or _utc_now()
    stale_after = (
        last_assistant_at
        if isinstance(last_assistant_at, datetime)
        else _utc_now()
    )

    user_count = _safe_int(state.get("user_message_count"), 0)
    has_click = bool(state.get("has_click"))
    has_download = bool(state.get("has_download"))

    if user_count == 1 and not has_click and not has_download:
        queued += await _queue_followup(
            db,
            user_id=user_id,
            external_user_id=external_user_id,
            conversation_id=conversation_id,
            chat_id=chat_id,
            trigger=TRIGGER_FIRST_IDLE,
            category_key="app_download_first_push",
            send_at=_utc_now()
            + timedelta(seconds=max(30, settings.APP_DOWNLOAD_FIRST_IDLE_SECONDS)),
            priority=60,
            stale_after=stale_after,
            rule_key=f"{TRIGGER_FIRST_IDLE}:{conversation_id}",
            trace_id=trace_id,
            account_id=sender_account_id,
        )

    if 3 <= user_count <= 5 and not has_click and not has_download:
        queued += await _queue_followup(
            db,
            user_id=user_id,
            external_user_id=external_user_id,
            conversation_id=conversation_id,
            chat_id=chat_id,
            trigger=TRIGGER_WARM_NO_CLICK,
            category_key="app_download_after_warmup",
            send_at=_utc_now()
            + timedelta(seconds=max(10, settings.APP_DOWNLOAD_WARM_NO_CLICK_SECONDS)),
            priority=80,
            stale_after=stale_after,
            rule_key=f"{TRIGGER_WARM_NO_CLICK}:{conversation_id}",
            trace_id=trace_id,
            account_id=sender_account_id,
        )

    if not has_download:
        queued += await _queue_followup(
            db,
            user_id=user_id,
            external_user_id=external_user_id,
            conversation_id=conversation_id,
            chat_id=chat_id,
            trigger=TRIGGER_SILENT_30M,
            category_key="app_download_after_warmup",
            send_at=_utc_now()
            + timedelta(seconds=max(60, settings.APP_DOWNLOAD_SILENT_30M_SECONDS)),
            priority=50,
            stale_after=stale_after,
            rule_key=f"{TRIGGER_SILENT_30M}:{assistant_message_id}",
            trace_id=trace_id,
            account_id=sender_account_id,
        )
        queued += await _queue_followup(
            db,
            user_id=user_id,
            external_user_id=external_user_id,
            conversation_id=conversation_id,
            chat_id=chat_id,
            trigger=TRIGGER_SILENT_24H,
            category_key="app_download_after_warmup",
            send_at=_utc_now()
            + timedelta(seconds=max(3600, settings.APP_DOWNLOAD_SILENT_24H_SECONDS)),
            priority=40,
            stale_after=stale_after,
            rule_key=f"{TRIGGER_SILENT_24H}:{assistant_message_id}",
            trace_id=trace_id,
            account_id=sender_account_id,
        )

    if queued:
        await db.commit()
        logger.bind(
            component="app_download_nurture",
            trace_id=trace_id,
            conversation_id=conversation_id,
            queued=queued,
        ).info("app_download_nurture.followups_queued")
    return queued


async def queue_clicked_not_downloaded_followups(
    db: AsyncSession,
    *,
    trace_id: str | None = None,
    batch_size: int = 20,
) -> int:
    if not settings.APP_DOWNLOAD_NURTURE_ENABLED:
        return 0

    rows = (
        await db.execute(
            text(
                """
                WITH clicked AS (
                    SELECT
                        l.tracking_id,
                        l.user_id::text AS user_id,
                        l.conversation_id::text AS conversation_id,
                        u.external_id AS external_user_id,
                        CASE
                            WHEN regexp_replace(u.external_id, '^tg_', '') ~ '^[0-9]+$'
                            THEN regexp_replace(u.external_id, '^tg_', '')::bigint
                            ELSE NULL
                        END AS chat_id,
                        MIN(e.created_at) FILTER (WHERE e.event_type = 'click') AS clicked_at
                    FROM attribution_links l
                    JOIN users u ON u.id = l.user_id
                    LEFT JOIN attribution_events e ON e.tracking_id = l.tracking_id
                    WHERE l.script_category IN (
                        'app_download_first_push',
                        'app_download_after_warmup',
                        'app_download_direct_cta',
                        'app_download_objection',
                        'trust_reassurance',
                        'app_link_clicked_followup',
                        'operator_app_conversion'
                    )
                    GROUP BY l.tracking_id, l.user_id, l.conversation_id, u.external_id
                    HAVING
                        MIN(e.created_at) FILTER (WHERE e.event_type = 'click') <= NOW() - (:delay_seconds * INTERVAL '1 second')
                        AND MIN(e.created_at) FILTER (WHERE e.event_type = 'click') >= NOW() - INTERVAL '24 hours'
                        AND COUNT(*) FILTER (WHERE e.event_type = 'download') = 0
                )
                SELECT *
                FROM clicked c
                WHERE c.conversation_id IS NOT NULL
                  AND c.chat_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM message_schedules ms
                      WHERE ms.metadata->>'delivery_mode' = :delivery_mode
                        AND ms.metadata->>'trigger' = :trigger
                        AND ms.metadata->>'tracking_id' = c.tracking_id
                        AND ms.status IN ('pending', 'sending', 'sent')
                  )
                ORDER BY c.clicked_at ASC
                LIMIT :batch_size
                """
            ),
            {
                "delay_seconds": max(60, settings.APP_DOWNLOAD_CLICK_NO_DOWNLOAD_SECONDS),
                "delivery_mode": APP_DOWNLOAD_NURTURE_DELIVERY_MODE,
                "trigger": TRIGGER_CLICK_NO_DOWNLOAD,
                "batch_size": max(1, batch_size),
            },
        )
    ).mappings().all()

    queued = 0
    for row in rows:
        data = dict(row)
        sender_account_id = await resolve_nurture_sender_account_id(
            db,
            conversation_id=str(data.get("conversation_id") or ""),
        )
        queued += await _queue_followup(
            db,
            user_id=str(data["user_id"]),
            external_user_id=str(data["external_user_id"]),
            conversation_id=str(data["conversation_id"]),
            chat_id=int(data["chat_id"]),
            trigger=TRIGGER_CLICK_NO_DOWNLOAD,
            category_key="app_link_clicked_followup",
            send_at=_utc_now(),
            priority=90,
            stale_after=None,
            rule_key=f"{TRIGGER_CLICK_NO_DOWNLOAD}:{data['tracking_id']}",
            trace_id=trace_id,
            account_id=sender_account_id,
            extra_metadata={"tracking_id": str(data["tracking_id"])},
        )

    if queued:
        await db.commit()
        logger.bind(
            component="app_download_nurture",
            trace_id=trace_id,
            queued=queued,
        ).info("app_download_nurture.clicked_followups_queued")
    return queued


async def should_skip_stale_nurture_message(
    db: AsyncSession,
    *,
    message: dict[str, Any],
) -> str | None:
    metadata = message.get("metadata") or {}
    if metadata.get("delivery_mode") != APP_DOWNLOAD_NURTURE_DELIVERY_MODE:
        return None

    if metadata.get("stop_if_downloaded", True):
        downloaded = (
            await db.execute(
                text(
                    """
                    SELECT 1
                    FROM attribution_links l
                    JOIN attribution_events e ON e.tracking_id = l.tracking_id
                    WHERE l.user_id = CAST(:user_id AS uuid)
                      AND l.conversation_id = CAST(:conversation_id AS uuid)
                      AND e.event_type = 'download'
                    LIMIT 1
                    """
                ),
                {
                    "user_id": message["user_id"],
                    "conversation_id": metadata.get("conversation_id"),
                },
            )
        ).fetchone()
        if downloaded:
            return "already_downloaded"

    stale_after = metadata.get("cancel_if_user_message_after")
    if stale_after:
        replied = (
            await db.execute(
                text(
                    """
                    SELECT 1
                    FROM messages
                    WHERE conversation_id = CAST(:conversation_id AS uuid)
                      AND sender_type = 'user'
                      AND created_at > CAST(:stale_after AS timestamptz)
                    LIMIT 1
                    """
                ),
                {
                    "conversation_id": metadata.get("conversation_id"),
                    "stale_after": stale_after,
                },
            )
        ).fetchone()
        if replied:
            return "user_replied_after_queue"

    return None


async def prepare_nurture_message_for_send(
    db: AsyncSession,
    *,
    message: dict[str, Any],
    trace_id: str | None,
) -> str:
    metadata = message.get("metadata") or {}
    content = str(message.get("content") or "")
    if metadata.get("delivery_mode") != APP_DOWNLOAD_NURTURE_DELIVERY_MODE:
        return content

    return await wrap_text_links_with_tracking(
        db,
        text_value=content,
        base_url=str(settings.PUBLIC_BASE_URL).rstrip("/"),
        user_id=message.get("user_id"),
        conversation_id=metadata.get("conversation_id"),
        message_id=None,
        script_hit_id=metadata.get("script_hit_id"),
        platform="telegram_real_user",
        scene_step=metadata.get("scene_step"),
        script_category=metadata.get("category_key"),
        persona_slug=metadata.get("persona_slug"),
        intent=metadata.get("intent"),
        country_code=metadata.get("country_code"),
        age=metadata.get("age"),
        user_level=metadata.get("user_level"),
        is_t1_country=metadata.get("is_t1_country"),
        metadata={"source": "app_download_nurture", "trace_id": trace_id},
    )


async def persist_auto_delivery_message(
    db: AsyncSession,
    *,
    message: dict[str, Any],
    content: str,
    sender_id: str,
) -> str | None:
    metadata = message.get("metadata") or {}
    conversation_id = metadata.get("conversation_id")
    if not conversation_id:
        return None
    row = (
        await db.execute(
            text(
                """
                INSERT INTO messages (
                    conversation_id, sender_type, sender_id, content, content_type,
                    model_name, created_at
                )
                VALUES (
                    CAST(:conversation_id AS uuid), 'assistant', :sender_id, :content,
                    'text', 'auto_delivery_worker', NOW()
                )
                RETURNING id
                """
            ),
            {
                "conversation_id": conversation_id,
                "sender_id": sender_id,
                "content": content,
            },
        )
    ).fetchone()
    await db.execute(
        text("UPDATE conversations SET last_message_at=NOW(), updated_at=NOW() WHERE id=CAST(:cid AS uuid)"),
        {"cid": conversation_id},
    )
    await db.commit()
    return str(row[0]) if row else None


async def resolve_nurture_sender_account_id(
    db: AsyncSession,
    *,
    conversation_id: str | None,
) -> str | None:
    """Return the MTProto account that last spoke in this conversation."""
    if not conversation_id:
        return None
    row = (
        await db.execute(
            text(
                """
                SELECT sender_id
                FROM messages
                WHERE conversation_id = CAST(:conversation_id AS uuid)
                  AND sender_type = 'assistant'
                  AND sender_id ~* '^[0-9a-f-]{36}$'
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"conversation_id": conversation_id},
        )
    ).fetchone()
    if not row or not row[0]:
        return None
    return str(row[0])


async def _queue_followup(
    db: AsyncSession,
    *,
    user_id: str,
    external_user_id: str,
    conversation_id: str,
    chat_id: int,
    trigger: str,
    category_key: str,
    send_at: datetime,
    priority: int,
    stale_after: datetime | None,
    rule_key: str,
    trace_id: str | None,
    account_id: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> int:
    content, script_meta = await _build_contextual_content(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        trigger=trigger,
        category_key=category_key,
        trace_id=trace_id,
    )
    if not content:
        return 0

    metadata = {
        "delivery_mode": APP_DOWNLOAD_NURTURE_DELIVERY_MODE,
        "trigger": trigger,
        "category_key": category_key,
        "conversation_id": conversation_id,
        "rule_key": rule_key,
        "cancel_if_user_message_after": (
            stale_after.isoformat() if isinstance(stale_after, datetime) else None
        ),
        "stop_if_downloaded": True,
        **script_meta,
        **(extra_metadata or {}),
    }
    if account_id:
        metadata["sender_account_id"] = account_id
    result = await db.execute(
        text(
            """
            INSERT INTO message_schedules (
                user_id, external_user_id, message_type, content, platform, chat_id,
                account_id, status, send_at, priority, metadata, trace_id
            )
            SELECT
                :user_id, :external_user_id, :message_type, :content,
                'telegram_real_user', :chat_id, :account_id, 'pending', :send_at, :priority,
                CAST(:metadata AS jsonb), :trace_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM message_schedules
                WHERE metadata->>'delivery_mode' = :delivery_mode
                  AND metadata->>'rule_key' = :rule_key
                  AND status IN ('pending', 'sending', 'sent')
            )
            RETURNING id
            """
        ),
        {
            "user_id": user_id,
            "external_user_id": external_user_id,
            "message_type": APP_DOWNLOAD_MESSAGE_TYPE,
            "content": content,
            "chat_id": chat_id,
            "account_id": account_id,
            "send_at": send_at,
            "priority": priority,
            "metadata": json.dumps(metadata, ensure_ascii=False),
            "trace_id": trace_id,
            "delivery_mode": APP_DOWNLOAD_NURTURE_DELIVERY_MODE,
            "rule_key": rule_key,
        },
    )
    return 1 if result.fetchone() else 0


async def _load_conversation_state(
    db: AsyncSession,
    *,
    user_id: str,
    conversation_id: str,
) -> dict[str, Any] | None:
    row = (
        await db.execute(
            text(
                """
                SELECT
                    COUNT(DISTINCT m.id) FILTER (WHERE m.sender_type = 'user') AS user_message_count,
                    MAX(m.created_at) FILTER (WHERE m.sender_type = 'user') AS last_user_at,
                    MAX(m.created_at) FILTER (WHERE m.sender_type IN ('assistant', 'ai', 'bot')) AS last_assistant_at,
                    COALESCE(bool_or(e.event_type = 'click'), FALSE) AS has_click,
                    COALESCE(bool_or(e.event_type = 'download'), FALSE) AS has_download
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.id
                LEFT JOIN attribution_links l ON l.conversation_id = c.id
                LEFT JOIN attribution_events e ON e.tracking_id = l.tracking_id
                WHERE c.id = CAST(:conversation_id AS uuid)
                  AND c.user_id = CAST(:user_id AS uuid)
                GROUP BY c.id
                """
            ),
            {"user_id": user_id, "conversation_id": conversation_id},
        )
    ).fetchone()
    return _row_dict(row)


async def _build_contextual_content(
    db: AsyncSession,
    *,
    user_id: str,
    conversation_id: str,
    trigger: str,
    category_key: str,
    trace_id: str | None,
) -> tuple[str, dict[str, Any]]:
    destination_url = await resolve_app_download_url(db)
    if not destination_url:
        return "", {}

    profile = await _load_profile(db, user_id=user_id)
    history = await _load_recent_messages(db, conversation_id=conversation_id)
    last_user_text = _last_user_text(history)
    context_line = _context_line(last_user_text)

    user_level = str((profile or {}).get("user_level") or "C").upper()
    persona_slug = (profile or {}).get("persona_slug")
    country_code = normalize_country_code((profile or {}).get("country_code") or _prefs(profile).get("country_code"))
    age = age_from_preferences(_prefs(profile))
    is_t1 = country_tier(country_code) == "T1" if country_code else None
    language = _language(profile, history)

    script_content, script_hit_id = await _select_script_content(
        db,
        category_key=category_key,
        user_level=user_level,
        persona_slug=persona_slug,
        language=language,
        query=last_user_text or trigger,
        trace_id=trace_id,
    )
    if not script_content:
        script_content = _fallback_template(trigger)

    content = _render_contextual_template(
        script_content,
        app_download_url=destination_url,
        context_line=context_line,
        trigger=trigger,
    )
    meta = {
        "script_hit_id": script_hit_id,
        "scene_step": trigger,
        "intent": trigger,
        "persona_slug": persona_slug,
        "country_code": country_code,
        "age": age,
        "user_level": user_level,
        "is_t1_country": is_t1,
        "language": language,
    }
    return content, meta


async def _select_script_content(
    db: AsyncSession,
    *,
    category_key: str,
    user_level: str,
    persona_slug: str | None,
    language: str,
    query: str,
    trace_id: str | None,
) -> tuple[str | None, str | None]:
    try:
        result = await search_script_templates(
            db=db,
            query=ScriptTemplateQuery(
                query=query,
                platform="telegram_real_user",
                user_level=user_level,
                persona_slug=persona_slug,
                hook="reply",
                category_key=category_key,
                language=language,
                limit=1,
            ),
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.bind(
            component="app_download_nurture",
            error_type=type(exc).__name__,
        ).warning("app_download_nurture.script_search_failed")
        return None, None
    if not result.hits:
        return None, None
    return result.hits[0].content, result.hits[0].id


async def _load_profile(db: AsyncSession, *, user_id: str) -> dict[str, Any] | None:
    row = (
        await db.execute(
            text("SELECT * FROM user_profiles WHERE user_id = CAST(:uid AS uuid)"),
            {"uid": user_id},
        )
    ).fetchone()
    return _row_dict(row)


async def _load_recent_messages(db: AsyncSession, *, conversation_id: str) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            text(
                """
                SELECT sender_type, content, created_at
                FROM messages
                WHERE conversation_id = CAST(:conversation_id AS uuid)
                  AND COALESCE(content, '') <> ''
                ORDER BY created_at DESC
                LIMIT 16
                """
            ),
            {"conversation_id": conversation_id},
        )
    ).mappings().all()
    return [dict(row) for row in reversed(rows)]


def _last_user_text(history: list[dict[str, Any]]) -> str:
    for row in reversed(history):
        if str(row.get("sender_type") or "").lower() == "user":
            return _clean_text(str(row.get("content") or ""))
    return ""


def _context_line(last_user_text: str) -> str:
    if not last_user_text:
        return ""
    trimmed = last_user_text[:120]
    return f"You said: \"{trimmed}\". "


def _render_contextual_template(
    template: str,
    *,
    app_download_url: str,
    context_line: str,
    trigger: str,
) -> str:
    body = str(template or "").replace("{{app_download_url}}", app_download_url).strip()
    if not body:
        body = _fallback_template(trigger).replace("{{app_download_url}}", app_download_url)
    if context_line and not _looks_contextual(body):
        body = f"{context_line}{body}"
    return body


def _fallback_template(trigger: str) -> str:
    if trigger == TRIGGER_FIRST_IDLE:
        return "I liked where this was going. When you are ready, open this and we can keep it private: {{app_download_url}}"
    if trigger == TRIGGER_CLICK_NO_DOWNLOAD:
        return "You already opened the door. Finish the download and I will keep chatting with you there: {{app_download_url}}"
    if trigger == TRIGGER_SILENT_24H:
        return "I remembered our last chat. Come back through here when you want to continue: {{app_download_url}}"
    return "Do not let the chat lose momentum. Open this and we will continue there: {{app_download_url}}"


def _looks_contextual(text_value: str) -> bool:
    lowered = text_value.lower()
    return any(word in lowered for word in ("you said", "you told", "earlier", "last time", "remember"))


def _clean_text(text_value: str) -> str:
    value = re.sub(r"\s+", " ", text_value or "").strip()
    return value.replace('"', "'")


def _prefs(profile: dict[str, Any] | None) -> dict[str, Any]:
    prefs = (profile or {}).get("preferences") or {}
    return prefs if isinstance(prefs, dict) else {}


def _language(profile: dict[str, Any] | None, history: list[dict[str, Any]]) -> str:
    value = (profile or {}).get("language") or _prefs(profile).get("language")
    if value:
        return "zh" if str(value).lower().startswith("zh") else "en"
    joined = " ".join(str(row.get("content") or "") for row in history[-4:])
    return "zh" if any("\u4e00" <= ch <= "\u9fff" for ch in joined) else "en"
