from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from services.app_download_platforms import resolve_app_download_url
from services.emotion_lexicon import detect_language_from_text
from services.level_engine import country_tier
from services.link_attribution import wrap_text_links_with_tracking
from services.profile_intake import age_from_preferences, normalize_country_code
from services.script_template_retriever import ScriptTemplateQuery, search_script_templates
from services.telegram_peer_cache import resolve_cached_telegram_peer


APP_DOWNLOAD_NURTURE_DELIVERY_MODE = "app_download_nurture"
APP_DOWNLOAD_MESSAGE_TYPE = "app_download_followup"
_LEGACY_USER_QUOTE_PREFIX = re.compile(r'^\s*You said:\s*"[^"]*"\.\s*', re.IGNORECASE)

# ── 培育 v3：沉默三轮，每轮先问要不要视频聊 ─────────────────────────────
# 助手回复后用户一直不说话 → 5min 第一轮 / 30min 第二轮 / 24h 第三轮
TRIGGER_NURTURE_ROUND_1 = "nurture_round_1"
TRIGGER_NURTURE_ROUND_2 = "nurture_round_2"
TRIGGER_NURTURE_ROUND_3 = "nurture_round_3"
NURTURE_KIND_VIDEO_CHAT = "video_chat"

_NURTURE_ROUND_TRIGGERS = (
    TRIGGER_NURTURE_ROUND_1,
    TRIGGER_NURTURE_ROUND_2,
    TRIGGER_NURTURE_ROUND_3,
)

# Legacy aliases
TRIGGER_IDLE_CLICK = TRIGGER_NURTURE_ROUND_1
TRIGGER_FIRST_IDLE = TRIGGER_NURTURE_ROUND_1
TRIGGER_ASSET_IDLE = TRIGGER_NURTURE_ROUND_1
TRIGGER_WARM_NO_CLICK = TRIGGER_NURTURE_ROUND_2
TRIGGER_SILENT_30M = TRIGGER_NURTURE_ROUND_2
TRIGGER_SILENT_24H = TRIGGER_NURTURE_ROUND_3

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


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text_value = value.strip()
    if text_value.endswith("Z"):
        text_value = f"{text_value[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text_value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _nurture_round_seconds(round_num: int) -> int:
    defaults = {1: 300, 2: 1800, 3: 86400}
    keys = {
        1: "APP_DOWNLOAD_NURTURE_ROUND1_SECONDS",
        2: "APP_DOWNLOAD_NURTURE_ROUND2_SECONDS",
        3: "APP_DOWNLOAD_NURTURE_ROUND3_SECONDS",
    }
    legacy = {
        1: "APP_DOWNLOAD_NURTURE_IDLE_SECONDS",
        2: "APP_DOWNLOAD_NURTURE_ROUND2_SECONDS",
        3: "APP_DOWNLOAD_SILENT_24H_SECONDS",
    }
    value = getattr(settings, keys[round_num], None)
    if value is None and round_num == 1:
        value = getattr(settings, legacy[1], None) or settings.APP_DOWNLOAD_FIRST_IDLE_SECONDS
    if value is None and round_num == 2:
        value = getattr(settings, legacy[2], None) or settings.APP_DOWNLOAD_SILENT_30M_SECONDS
    if value is None and round_num == 3:
        value = getattr(settings, legacy[3], None) or settings.APP_DOWNLOAD_SILENT_24H_SECONDS
    return max(60, int(value or defaults[round_num]))


def _round_trigger(round_num: int) -> str:
    return {
        1: TRIGGER_NURTURE_ROUND_1,
        2: TRIGGER_NURTURE_ROUND_2,
        3: TRIGGER_NURTURE_ROUND_3,
    }[round_num]


def _round_category_key(round_num: int) -> str:
    return f"nurture_video_round_{round_num}"


def _normalize_nurture_language(detected: str | None) -> str:
    value = str(detected or "en").lower()
    if value.startswith("zh"):
        return "zh"
    if value in {"es", "pt"}:
        return value
    return "en"


_ES_NURTURE_RE = re.compile(
    r"\b(hola|quiero|mi\s+vida|llamada|videollamada|ver|mañana|depois)\b",
    re.IGNORECASE | re.UNICODE,
)
_PT_NURTURE_RE = re.compile(
    r"\b(oi|quero|você|voce|chamada|vídeo|video|cadê|cade|amanhã|amanha)\b",
    re.IGNORECASE | re.UNICODE,
)


def detect_nurture_language_from_text(text_value: str | None) -> str:
    text = str(text_value or "").strip()
    if not text:
        return "en"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    if _ES_NURTURE_RE.search(text):
        return "es"
    if _PT_NURTURE_RE.search(text):
        return "pt"
    return _normalize_nurture_language(detect_language_from_text(text, default="en"))


async def persist_user_nurture_language(
    db: AsyncSession,
    *,
    user_id: str,
    conversation_id: str,
    language: str,
) -> None:
    await db.execute(
        text(
            """
            UPDATE user_profiles
            SET preferences = COALESCE(preferences, '{}'::jsonb)
                || jsonb_build_object('nurture_language', CAST(:language AS text)),
                updated_at = NOW()
            WHERE user_id = CAST(:user_id AS uuid)
            """
        ),
        {
            "user_id": user_id,
            "language": _normalize_nurture_language(language),
        },
    )


def _video_chat_round_copy(round_num: int, language: str) -> str:
    copies: dict[int, dict[str, str]] = {
        1: {
            "en": "Still here? Tap call on my profile for a quick video.",
            "zh": "我还在呢，点我资料页的视频通话打过来，聊一小会儿？",
            "es": "Sigo aquí. Toca videollamada en mi perfil si quieres hablar ahora.",
            "pt": "Ainda estou aqui. Toca em chamada de vídeo no meu perfil se quiser conversar.",
        },
        2: {
            "en": "I was waiting for you. Tap call on my profile — I'll pick up.",
            "zh": "我刚刚还在等你，点我资料页的视频通话打过来，我会接。",
            "es": "Te estaba esperando. Toca videollamada en mi perfil y te contesto.",
            "pt": "Eu estava te esperando. Toca na chamada do meu perfil que eu atendo.",
        },
        3: {
            "en": "I liked talking with you yesterday. Tap call on my profile tonight if you're free.",
            "zh": "昨天聊得挺开心，今晚有空就点我资料页的视频打过来。",
            "es": "Me gustó hablar contigo ayer. Esta noche toca videollamada en mi perfil si puedes.",
            "pt": "Gostei de falar com você ontem. Hoje à noite toca em chamada no meu perfil se puder.",
        },
    }
    lang = _normalize_nurture_language(language)
    return copies.get(round_num, copies[1]).get(lang, copies[round_num]["en"])


async def schedule_nurture_after_reply(
    db: AsyncSession,
    *,
    user_id: str,
    external_user_id: str,
    conversation_id: str,
    chat_id: int | None,
    assistant_message_id: str,
    trace_id: str | None,
    account_id: str | None = None,
    telegram_access_hash: int | None = None,
    source: str = "reply",
) -> int:
    """培育 v3：助手回复后，按沉默时长排三轮视频聊邀请。

    第一轮 5 分钟 / 第二轮 30 分钟 / 第三轮 24 小时。
    任一轮发送前用户若再次发言则取消（stale guard）。
    """
    if not settings.APP_DOWNLOAD_NURTURE_ENABLED or not chat_id:
        return 0

    sender_account_id = account_id or await resolve_nurture_sender_account_id(
        db,
        conversation_id=conversation_id,
    )
    cached_peer = await resolve_cached_telegram_peer(
        db,
        conversation_id=conversation_id,
        user_id=user_id,
        account_id=sender_account_id,
        chat_id=chat_id,
    )
    if cached_peer:
        sender_account_id = sender_account_id or cached_peer.get("account_id")
        if telegram_access_hash is None and cached_peer.get("access_hash") is not None:
            telegram_access_hash = int(cached_peer["access_hash"])

    state = await _load_conversation_state(db, user_id=user_id, conversation_id=conversation_id)
    if not state:
        return 0
    if bool(state.get("has_download")):
        return 0

    last_assistant_at = state.get("last_assistant_at") or _utc_now()
    stale_after = last_assistant_at if isinstance(last_assistant_at, datetime) else _utc_now()

    lock_holder = await _pending_nurture_sender_lock(
        db,
        conversation_id=conversation_id,
        sender_account_id=sender_account_id,
    )
    if lock_holder:
        logger.bind(
            component="app_download_nurture",
            trace_id=trace_id,
            conversation_id=conversation_id,
            lock_holder=lock_holder,
            sender_account_id=sender_account_id,
        ).info("app_download_nurture.sender_lock_skip")
        return 0

    await _cancel_superseded_round_followups(
        db,
        conversation_id=conversation_id,
        assistant_message_id=assistant_message_id,
        sender_account_id=sender_account_id,
    )

    queued = 0
    now = _utc_now()
    round_extra: dict[str, Any] = {
        "source": source,
        "assistant_message_id": assistant_message_id,
        "nurture_kind": NURTURE_KIND_VIDEO_CHAT,
    }
    if telegram_access_hash is not None:
        round_extra["telegram_access_hash"] = str(int(telegram_access_hash))
    for round_num, priority in ((1, 85), (2, 75), (3, 65)):
        rule_key = f"{_round_trigger(round_num)}:{conversation_id}:{assistant_message_id}"
        queued += await _upsert_round_followup(
            db,
            user_id=user_id,
            external_user_id=external_user_id,
            conversation_id=conversation_id,
            chat_id=chat_id,
            round_num=round_num,
            send_at=now + timedelta(seconds=_nurture_round_seconds(round_num)),
            stale_after=stale_after,
            rule_key=rule_key,
            trace_id=trace_id,
            account_id=sender_account_id,
            priority=priority,
            extra_metadata=round_extra,
        )

    if queued:
        await db.commit()
        logger.bind(
            component="app_download_nurture",
            trace_id=trace_id,
            conversation_id=conversation_id,
            queued=queued,
            source=source,
        ).info("app_download_nurture.video_rounds_queued")
    return queued


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
    telegram_access_hash: int | None = None,
) -> int:
    return await schedule_nurture_after_reply(
        db,
        user_id=user_id,
        external_user_id=external_user_id,
        conversation_id=conversation_id,
        chat_id=chat_id,
        assistant_message_id=assistant_message_id,
        trace_id=trace_id,
        account_id=account_id,
        telegram_access_hash=telegram_access_hash,
        source="reply",
    )


async def schedule_asset_keyword_followup_after_reply(
    db: AsyncSession,
    *,
    user_id: str,
    external_user_id: str,
    conversation_id: str,
    chat_id: int | None,
    assistant_message_id: str,
    trace_id: str | None,
    account_id: str | None = None,
    telegram_access_hash: int | None = None,
) -> int:
    return await schedule_nurture_after_reply(
        db,
        user_id=user_id,
        external_user_id=external_user_id,
        conversation_id=conversation_id,
        chat_id=chat_id,
        assistant_message_id=assistant_message_id,
        trace_id=trace_id,
        account_id=account_id,
        telegram_access_hash=telegram_access_hash,
        source="asset_keyword",
    )


async def _cancel_superseded_round_followups(
    db: AsyncSession,
    *,
    conversation_id: str,
    assistant_message_id: str,
    sender_account_id: str | None = None,
) -> None:
    await db.execute(
        text(
            """
            UPDATE message_schedules
            SET status = 'failed',
                failure_reason = 'superseded:new_assistant_reply',
                updated_at = NOW()
            WHERE metadata->>'delivery_mode' = :delivery_mode
              AND metadata->>'conversation_id' = :conversation_id
              AND metadata->>'trigger' = ANY(:triggers)
              AND status = 'pending'
              AND COALESCE(metadata->>'assistant_message_id', '') <> :assistant_message_id
              AND COALESCE(metadata->>'sender_account_id', '') = COALESCE(:sender_account_id, '')
            """
        ),
        {
            "delivery_mode": APP_DOWNLOAD_NURTURE_DELIVERY_MODE,
            "conversation_id": conversation_id,
            "assistant_message_id": assistant_message_id,
            "sender_account_id": sender_account_id,
            "triggers": list(_NURTURE_ROUND_TRIGGERS),
        },
    )


async def _build_video_round_content(
    db: AsyncSession,
    *,
    user_id: str,
    conversation_id: str,
    round_num: int,
    trace_id: str | None,
) -> tuple[str, dict[str, Any]]:
    profile = await _load_profile(db, user_id=user_id)
    history = await _load_recent_messages(db, conversation_id=conversation_id)
    user_level = str((profile or {}).get("user_level") or "C").upper()
    persona_slug = (profile or {}).get("persona_slug")
    country_code = normalize_country_code((profile or {}).get("country_code") or _prefs(profile).get("country_code"))
    age = age_from_preferences(_prefs(profile))
    is_t1 = country_tier(country_code) == "T1" if country_code else None
    language = _nurture_reply_language(history, profile=profile)
    category_key = _round_category_key(round_num)
    trigger = _round_trigger(round_num)

    script_content, script_hit_id = await _select_script_content(
        db,
        category_key=category_key,
        user_level=user_level,
        persona_slug=persona_slug,
        language=language,
        query=_last_user_text(history) or trigger,
        trace_id=trace_id,
        ab_seed=conversation_id,
    )
    content = (script_content or _video_chat_round_copy(round_num, language)).strip()
    content = _strip_legacy_user_quote_prefix(content)
    return content, {
        "script_hit_id": script_hit_id,
        "scene_step": trigger,
        "intent": trigger,
        "persona_slug": persona_slug,
        "country_code": country_code,
        "age": age,
        "user_level": user_level,
        "is_t1_country": is_t1,
        "language": language,
        "category_key": category_key,
        "nurture_round": round_num,
    }


async def _upsert_round_followup(
    db: AsyncSession,
    *,
    user_id: str,
    external_user_id: str,
    conversation_id: str,
    chat_id: int,
    round_num: int,
    send_at: datetime,
    stale_after: datetime,
    rule_key: str,
    trace_id: str | None,
    account_id: str | None,
    priority: int,
    extra_metadata: dict[str, Any] | None = None,
) -> int:
    content, script_meta = await _build_video_round_content(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        round_num=round_num,
        trace_id=trace_id,
    )
    if not content:
        return 0

    trigger = _round_trigger(round_num)
    metadata = {
        "delivery_mode": APP_DOWNLOAD_NURTURE_DELIVERY_MODE,
        "trigger": trigger,
        "category_key": _round_category_key(round_num),
        "conversation_id": conversation_id,
        "rule_key": rule_key,
        "cancel_if_user_message_after": stale_after.isoformat(),
        "stop_if_downloaded": True,
        "nurture_kind": NURTURE_KIND_VIDEO_CHAT,
        **script_meta,
        **(extra_metadata or {}),
    }
    if account_id:
        metadata["sender_account_id"] = account_id

    updated = (
        await db.execute(
            text(
                """
                UPDATE message_schedules
                SET content = :content,
                    send_at = :send_at,
                    priority = :priority,
                    metadata = CAST(:metadata AS jsonb),
                    trace_id = :trace_id,
                    account_id = :account_id,
                    updated_at = NOW()
                WHERE metadata->>'delivery_mode' = :delivery_mode
                  AND metadata->>'rule_key' = :rule_key
                  AND status = 'pending'
                RETURNING id
                """
            ),
            {
                "content": content,
                "send_at": send_at,
                "priority": priority,
                "metadata": json.dumps(metadata, ensure_ascii=False),
                "trace_id": trace_id,
                "account_id": account_id,
                "delivery_mode": APP_DOWNLOAD_NURTURE_DELIVERY_MODE,
                "rule_key": rule_key,
            },
        )
    ).fetchone()
    if updated:
        return 1

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


async def queue_clicked_not_downloaded_followups(
    db: AsyncSession,
    *,
    trace_id: str | None = None,
    batch_size: int = 20,
) -> int:
    """Disabled: click≠install cannot be inferred reliably."""
    return 0


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

    stale_after = _coerce_datetime(metadata.get("cancel_if_user_message_after"))
    if stale_after:
        from services.nurture_reply_handler import is_spam_reply

        rows = (
            await db.execute(
                text(
                    """
                    SELECT content
                    FROM messages
                    WHERE conversation_id = CAST(:conversation_id AS uuid)
                      AND sender_type = 'user'
                      AND created_at > CAST(:stale_after AS timestamptz)
                    ORDER BY created_at ASC
                    """
                ),
                {
                    "conversation_id": metadata.get("conversation_id"),
                    "stale_after": stale_after,
                },
            )
        ).fetchall()
        for row in rows:
            content = row[0] if not hasattr(row, "_mapping") else row._mapping.get("content")
            if content and not is_spam_reply(str(content)):
                return "user_replied_after_queue"

    return None


async def prepare_nurture_message_for_send(
    db: AsyncSession,
    *,
    message: dict[str, Any],
    trace_id: str | None,
) -> str:
    metadata = message.get("metadata") or {}
    if metadata.get("delivery_mode") != APP_DOWNLOAD_NURTURE_DELIVERY_MODE:
        return str(message.get("content") or "")

    if metadata.get("nurture_kind") == NURTURE_KIND_VIDEO_CHAT:
        conversation_id = metadata.get("conversation_id")
        user_id = message.get("user_id")
        round_num = int(metadata.get("nurture_round") or 1)
        if conversation_id and user_id:
            content, _ = await _build_video_round_content(
                db,
                user_id=str(user_id),
                conversation_id=str(conversation_id),
                round_num=round_num,
                trace_id=trace_id,
            )
            if content:
                return content

    content = str(message.get("content") or "")
    if "http" not in content:
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
                  AND status IN ('pending', 'sending', 'sent', 'failed')
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
    context_line = ""

    user_level = str((profile or {}).get("user_level") or "C").upper()
    persona_slug = (profile or {}).get("persona_slug")
    country_code = normalize_country_code((profile or {}).get("country_code") or _prefs(profile).get("country_code"))
    age = age_from_preferences(_prefs(profile))
    is_t1 = country_tier(country_code) == "T1" if country_code else None
    language = _nurture_reply_language(history, profile=profile)

    script_content: str | None = None
    script_hit_id: str | None = None
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
    content = _strip_legacy_user_quote_prefix(content)
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


def _pick_ab_script_hit(hits: list[Any], *, seed: str) -> Any | None:
    if not hits:
        return None
    digest = hashlib.md5(str(seed or "").encode("utf-8")).hexdigest()
    idx = int(digest, 16) % len(hits)
    return hits[idx]


async def _select_script_content(
    db: AsyncSession,
    *,
    category_key: str,
    user_level: str,
    persona_slug: str | None,
    language: str,
    query: str,
    trace_id: str | None,
    ab_seed: str | None = None,
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
                limit=8,
            ),
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.bind(
            component="app_download_nurture",
            error_type=type(exc).__name__,
        ).warning("app_download_nurture.script_search_failed")
        return None, None
    hit = _pick_ab_script_hit(result.hits, seed=ab_seed or category_key)
    if not hit:
        return None, None
    return hit.content, hit.id


async def _pending_nurture_sender_lock(
    db: AsyncSession,
    *,
    conversation_id: str,
    sender_account_id: str | None,
) -> str | None:
    row = (
        await db.execute(
            text(
                """
                SELECT metadata->>'sender_account_id' AS sender_account_id
                FROM message_schedules
                WHERE metadata->>'delivery_mode' = :delivery_mode
                  AND metadata->>'conversation_id' = :conversation_id
                  AND metadata->>'nurture_kind' = :nurture_kind
                  AND metadata->>'trigger' = ANY(:triggers)
                  AND status = 'pending'
                ORDER BY send_at ASC
                LIMIT 1
                """
            ),
            {
                "delivery_mode": APP_DOWNLOAD_NURTURE_DELIVERY_MODE,
                "conversation_id": conversation_id,
                "nurture_kind": NURTURE_KIND_VIDEO_CHAT,
                "triggers": list(_NURTURE_ROUND_TRIGGERS),
            },
        )
    ).fetchone()
    if not row:
        return None
    holder = str(row[0] if not hasattr(row, "_mapping") else row._mapping.get("sender_account_id") or "")
    if not holder:
        return None
    if sender_account_id and holder == str(sender_account_id):
        return None
    return holder


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
    return ""


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
    if trigger == TRIGGER_NURTURE_ROUND_1:
        return _video_chat_round_copy(1, "en")
    if trigger == TRIGGER_NURTURE_ROUND_2:
        return _video_chat_round_copy(2, "en")
    if trigger == TRIGGER_NURTURE_ROUND_3:
        return _video_chat_round_copy(3, "en")
    return _video_chat_round_copy(1, "en")


def _looks_contextual(text_value: str) -> bool:
    lowered = text_value.lower()
    return any(word in lowered for word in ("you said", "you told", "earlier", "last time", "remember"))


def _strip_legacy_user_quote_prefix(text_value: str) -> str:
    return _LEGACY_USER_QUOTE_PREFIX.sub("", text_value or "").strip()


def _clean_text(text_value: str) -> str:
    value = re.sub(r"\s+", " ", text_value or "").strip()
    return value.replace('"', "'")


def _nurture_reply_language(
    history: list[dict[str, Any]],
    *,
    profile: dict[str, Any] | None = None,
) -> str:
    """Use the user's last 3 messages; profile language is fallback only."""
    user_texts: list[str] = []
    for row in reversed(history):
        if str(row.get("sender_type") or "").lower() != "user":
            continue
        text = _clean_text(str(row.get("content") or ""))
        if not text:
            continue
        user_texts.append(text)
        if len(user_texts) >= 3:
            break

    if not user_texts:
        prefs = _prefs(profile)
        for key in ("nurture_language", "language", "lang"):
            pref = prefs.get(key) or (profile or {}).get(key)
            if pref:
                return _normalize_nurture_language(str(pref))
        return "en"

    votes: dict[str, int] = {}
    for idx, text in enumerate(user_texts):
        bucket = detect_nurture_language_from_text(text)
        votes[bucket] = votes.get(bucket, 0) + (3 - idx)

    ranked = sorted(votes.items(), key=lambda item: (-item[1], item[0]))
    if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
        return ranked[0][0]
    return detect_nurture_language_from_text(user_texts[0])


def _prefs(profile: dict[str, Any] | None) -> dict[str, Any]:
    prefs = (profile or {}).get("preferences") or {}
    return prefs if isinstance(prefs, dict) else {}
