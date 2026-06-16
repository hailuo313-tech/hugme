"""Runtime MTProto inbound handler that reads, thinks, and replies."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

import redis.asyncio as aioredis
from loguru import logger
from sqlalchemy import text

from core.config import settings
from core.database import AsyncSessionLocal
from services.memory_writer import maybe_write_memory
from services.llm_orchestrator import LLMOrchestratorError, generate_reply
from services.app_download_conversion import (
    decision_bypasses_link_cooldown,
    get_last_app_download_decision,
)
from services.link_cooldown import is_conversation_link_cooldown_active, strip_links_from_reply
from services.link_attribution import render_tracking_links_as_html_cta, wrap_text_links_with_tracking
from services.emotion_lexicon import detect_language_from_text, normalize_language
from services.profile_intake import (
    country_from_recent_user_messages,
    country_from_locale,
    country_from_text_language,
    extract_age_from_text,
    normalize_country_code,
    read_profile_completeness,
    write_age,
    write_country_code,
)
from services.reply_sanitize import sanitize_outbound_reply
from services.script_asset_delivery import send_mtproto_asset
from services.user_request_intent import (
    bypasses_link_cooldown,
    forces_app_download_script,
    is_media_asset_request,
    is_trust_reassurance_request,
)
from services.video_request_handoff import maybe_queue_live_video_call_operator_review
from services.app_download_nurture import schedule_nurture_after_reply
from services.nurture_reply_handler import handle_nurture_user_reply
from services.telegram_peer_cache import upsert_telegram_peer_cache
from services.user_level_service import user_level_service
from services.user_reply_guard import user_allows_auto_reply
from services.human_takeover_gate import evaluate_human_takeover_gate
from services.mtproto.account_routing import ensure_mtproto_account_route_for_reply
from services.message_repeat_guard import should_skip_duplicate_outbound
from services.mtproto.human_like_send import HumanLikeSendPolicy, send_human_like_message


CONTEXT_MAX_MESSAGES = 50
CONTEXT_TTL_SECONDS = 86400 * 3
INBOUND_READ_ACK_DELAY_SECONDS = 4.0
PROFILE_COUNTRY_QUESTION = (
    "Before we continue, which country are you in? You can reply with a country name "
    "or code, like US, Canada, Japan, or Germany."
)
PROFILE_COUNTRY_RETRY = (
    "I could not recognize that country. Please reply with your country name or a "
    "two-letter code, like US, GB, JP, or SG."
)
PROFILE_AGE_QUESTION = "Thanks. How old are you?"
PROFILE_AGE_RETRY = "Lmao you completely ignored my question! How old are you anyway? Tell me a number so I know if you're a big boy or just a baby. 😜"

_PROFILE_COPY = {
    "es": {
        "country_question": "Antes de seguir, ¿en qué país estás? Puedes responder con el país o el código, como US, Canada, Japan o Germany.",
        "country_retry": "No pude reconocer ese país. Responde con el nombre de tu país o un código de dos letras, como US, GB, JP o SG.",
        "age_question": "Gracias. ¿Cuántos años tienes?",
        "age_retry": "Responde con tu edad en número, por ejemplo 24.",
    },
    "pt": {
        "country_question": "Antes de continuar, em que país você está? Pode responder com o país ou o código, como US, Canada, Japan ou Germany.",
        "country_retry": "Não consegui reconhecer esse país. Responda com o nome do país ou um código de duas letras, como US, GB, JP ou SG.",
        "age_question": "Obrigado. Quantos anos você tem?",
        "age_retry": "Responda com sua idade em número, por exemplo 24.",
    },
    "ja": {
        "country_question": "続ける前に、どの国にいますか？US、Canada、Japan、Germany のように国名かコードで答えてください。",
        "country_retry": "その国を認識できませんでした。US、GB、JP、SG のように国名か2文字コードで答えてください。",
        "age_question": "ありがとう。何歳ですか？",
        "age_retry": "年齢を数字で答えてください。例: 24",
    },
    "ko": {
        "country_question": "계속하기 전에 어느 나라에 있나요? US, Canada, Japan, Germany처럼 나라 이름이나 코드로 답해 주세요.",
        "country_retry": "그 국가는 인식하지 못했어요. US, GB, JP, SG처럼 국가명이나 두 글자 코드로 답해 주세요.",
        "age_question": "고마워요. 몇 살인가요?",
        "age_retry": "나이를 숫자로 답해 주세요. 예: 24",
    },
}


def _profile_copy(kind: str, text_value: str, fallback: str) -> str:
    language = normalize_language(
        detect_language_from_text(text_value or "", default="en"),
        default="en",
    )
    return _PROFILE_COPY.get(language, {}).get(kind, fallback)

_redis_client = None

MTProtoReplyPolicy = HumanLikeSendPolicy(
    short_text_seconds=3.0,
    medium_text_seconds=6.0,
    long_text_seconds=10.0,
    very_long_text_seconds=15.0,
    minimum_typing_seconds=3.0,
    minimum_inter_message_seconds=0.0,
    typing_start_delay_seconds=5.0,
)


async def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL, encoding="utf-8", decode_responses=True
        )
    return _redis_client


def _trace_id(message_id: str | None) -> str:
    suffix = message_id or uuid.uuid4().hex[:8]
    return f"mtproto-{suffix}-{uuid.uuid4().hex[:10]}"


def _reply_delay_policy(reply_text: str) -> HumanLikeSendPolicy:
    size = len(reply_text or "")
    if size <= 10:
        delay = 3.0
    elif size <= 30:
        delay = 6.0
    elif size <= 50:
        delay = 10.0
    elif size <= 100:
        delay = 15.0
    elif size <= 200:
        delay = 25.0
    else:
        delay = 30.0
    return HumanLikeSendPolicy(
        short_text_seconds=delay,
        medium_text_seconds=delay,
        long_text_seconds=delay,
        very_long_text_seconds=delay,
        minimum_typing_seconds=delay,
        minimum_inter_message_seconds=0.0,
        typing_start_delay_seconds=5.0,
    )


async def _mark_read_after_delay(
    client: Any,
    event: Any,
    message: Any,
    log: Any,
    *,
    sleep: Any = asyncio.sleep,
) -> None:
    """Delay Telegram read receipt so the account does not read instantly."""
    if INBOUND_READ_ACK_DELAY_SECONDS > 0:
        await sleep(INBOUND_READ_ACK_DELAY_SECONDS)
    try:
        await client.send_read_acknowledge(getattr(event, "chat_id", None), message=message)
        log.info("mtproto.inbound.mark_read")
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("mtproto.inbound.mark_read_failed")


async def _push_context(redis, conv_id: str, role: str, content: str, msg_id: str) -> None:
    key = f"ctx:{conv_id}"
    entry = json.dumps(
        {"role": role, "content": content, "msg_id": msg_id, "ts": int(time.time())},
        ensure_ascii=False,
    )
    pipe = redis.pipeline()
    pipe.rpush(key, entry)
    pipe.ltrim(key, -CONTEXT_MAX_MESSAGES, -1)
    pipe.expire(key, CONTEXT_TTL_SECONDS)
    await pipe.execute()


def _spawn_memory_write(
    *,
    user_id: str,
    conv_id: str,
    msg_id: str,
    content: str,
    trace_id: str,
    redis: Any,
    log: Any,
    source: str,
) -> None:
    """Fire-and-forget memory write for MTProto without blocking chat flow."""
    try:
        asyncio.create_task(
            maybe_write_memory(
                user_id=user_id,
                conversation_id=conv_id,
                message_id=msg_id,
                content=content,
                trace_id=trace_id,
                redis=redis,
                is_onboarding=False,
            )
        )
        log.bind(message_id=msg_id, source=source).info("mtproto.memory_writer.spawned")
    except Exception as exc:
        log.bind(
            message_id=msg_id,
            source=source,
            error_type=type(exc).__name__,
        ).warning("mtproto.memory_writer.spawn_failed")


async def _get_or_create_user_and_conversation(
    *,
    external_id: str,
    nickname: str | None,
) -> tuple[str, str]:
    async with AsyncSessionLocal() as db:
        user_row = (
            await db.execute(
                text(
                    "INSERT INTO users "
                    "(channel, external_id, nickname, age_verified, status, created_at, updated_at) "
                    "VALUES ('telegram_real_user', :external_id, :nickname, true, 'active', NOW(), NOW()) "
                    "ON CONFLICT (channel, external_id) DO UPDATE SET updated_at=NOW() "
                    "RETURNING id"
                ),
                {"external_id": external_id, "nickname": nickname},
            )
        ).fetchone()
        user_id = str(user_row[0])

        await db.execute(
            text(
                "INSERT INTO user_profiles "
                "(user_id, preferences, chat_style, user_level, chat_route, updated_at) "
                "VALUES (:uid, CAST(:prefs AS jsonb), 'casual', 'C', 'ai_auto', NOW()) "
                "ON CONFLICT (user_id) DO UPDATE SET "
                "preferences = user_profiles.preferences || CAST(:prefs AS jsonb), "
                "updated_at=NOW()"
            ),
            {
                "uid": user_id,
                "prefs": json.dumps({"onboarding_step": 6}, ensure_ascii=False),
            },
        )

        if not await user_allows_auto_reply(db, user_id):
            await db.commit()
            return user_id, ""

        conv_row = (
            await db.execute(
                text(
                    "SELECT id FROM conversations "
                    "WHERE user_id=:uid AND state NOT IN ('CLOSED','ESCALATED','FROZEN') "
                    "ORDER BY updated_at DESC LIMIT 1"
                ),
                {"uid": user_id},
            )
        ).fetchone()
        if conv_row:
            conv_id = str(conv_row[0])
        else:
            conv_id = str(uuid.uuid4())
            await db.execute(
                text(
                    "INSERT INTO conversations (id, user_id, channel, state, created_at, updated_at) "
                    "VALUES (:cid, :uid, 'telegram_real_user', 'AI_ACTIVE', NOW(), NOW())"
                ),
                {"cid": conv_id, "uid": user_id},
            )

        await db.commit()
        return user_id, conv_id


async def _profile_preferences(db: Any, *, user_id: str) -> dict[str, Any]:
    row = (
        await db.execute(
            text("SELECT preferences FROM user_profiles WHERE user_id = CAST(:uid AS uuid)"),
            {"uid": user_id},
        )
    ).fetchone()
    if row is None:
        return {}
    data = row._mapping if hasattr(row, "_mapping") else row
    value = data.get("preferences") if hasattr(data, "get") else row[0]
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


async def _ensure_user_profile_row(db: Any, *, user_id: str) -> None:
    await db.execute(
        text(
            """
            INSERT INTO user_profiles
            (user_id, preferences, chat_style, user_level, chat_route, updated_at)
            VALUES (CAST(:uid AS uuid), '{}'::jsonb, 'casual', 'C', 'ai_auto', NOW())
            ON CONFLICT (user_id) DO NOTHING
            """
        ),
        {"uid": user_id},
    )


async def _write_profile_preferences(db: Any, *, user_id: str, preferences: dict[str, Any]) -> None:
    await _ensure_user_profile_row(db, user_id=user_id)
    await db.execute(
        text(
            """
            UPDATE user_profiles
            SET preferences = COALESCE(preferences, '{}'::jsonb) || CAST(:prefs AS jsonb),
                updated_at = NOW()
            WHERE user_id = CAST(:uid AS uuid)
            """
        ),
        {"uid": user_id, "prefs": json.dumps(preferences, ensure_ascii=False)},
    )


async def _persist_technical_country_hint(
    db: Any,
    *,
    user_id: str,
    sender: Any,
    log: Any,
) -> None:
    code = country_from_locale(
        getattr(sender, "lang_code", None)
        or getattr(sender, "language_code", None)
        or getattr(sender, "lang", None)
    )
    if not code:
        return
    completeness = await read_profile_completeness(db, user_id=user_id)
    if completeness.country_code:
        return
    await write_country_code(
        db,
        user_id=user_id,
        country_code=code,
        source="telegram_language_code",
    )
    await db.commit()
    log.bind(country_code=code).info("mtproto.profile.country_detected")


async def _handle_required_profile_intake(
    db: Any,
    *,
    user_id: str,
    external_id: str,
    text_value: str,
    log: Any,
) -> str | None:
    """Persist profile answers when present and return a non-blocking follow-up question."""
    await _ensure_user_profile_row(db, user_id=user_id)
    prefs = await _profile_preferences(db, user_id=user_id)
    pending = str(prefs.get("profile_intake_pending") or "").strip()
    completeness = await read_profile_completeness(db, user_id=user_id)

    if pending == "country":
        country_code = normalize_country_code(text_value)
        if not country_code:
            country_code = await country_from_recent_user_messages(
                db,
                user_id=user_id,
            )
        if not country_code:
            log.info("mtproto.profile.country_still_missing_continue_chat")
            return None
        await write_country_code(
            db,
            user_id=user_id,
            country_code=country_code,
            source="chat_answer",
        )
        prefs["profile_intake_pending"] = "age"
        await _write_profile_preferences(db, user_id=user_id, preferences=prefs)
        await db.commit()
        try:
            await user_level_service.calculate_and_persist_user_level(
                db,
                user_id=user_id,
                external_user_id=external_id,
                country_code=country_code,
            )
            await db.commit()
        except Exception as exc:
            rollback = getattr(db, "rollback", None)
            if rollback is not None:
                await rollback()
            log.bind(error_type=type(exc).__name__).warning(
                "mtproto.profile.level_recalc_failed"
            )
        log.bind(country_code=country_code).info("mtproto.profile.country_collected")
        return _profile_copy("age_question", text_value, PROFILE_AGE_QUESTION)

    if pending == "age":
        age = extract_age_from_text(text_value)
        if age is None:
            log.info("mtproto.profile.age_still_missing")
            return _profile_copy("age_retry", text_value, PROFILE_AGE_RETRY)
        await write_age(db, user_id=user_id, age=age, source="chat_answer")
        prefs.pop("profile_intake_pending", None)
        await _write_profile_preferences(db, user_id=user_id, preferences=prefs)
        await db.commit()
        try:
            await user_level_service.calculate_and_persist_user_level(
                db,
                user_id=user_id,
                external_user_id=external_id,
            )
            await db.commit()
        except Exception as exc:
            rollback = getattr(db, "rollback", None)
            if rollback is not None:
                await rollback()
            log.bind(error_type=type(exc).__name__).warning(
                "mtproto.profile.level_recalc_failed"
            )
        log.bind(age=age).info("mtproto.profile.age_collected")
        return None

    if completeness.country_code is None:
        inferred_country = (
            normalize_country_code(text_value)
            or await country_from_recent_user_messages(db, user_id=user_id)
            or country_from_text_language(text_value)
        )
        if inferred_country:
            await write_country_code(
                db,
                user_id=user_id,
                country_code=inferred_country,
                source="language_fallback",
            )
            await db.commit()
            try:
                await user_level_service.calculate_and_persist_user_level(
                    db,
                    user_id=user_id,
                    external_user_id=external_id,
                    country_code=inferred_country,
                )
                await db.commit()
            except Exception as exc:
                rollback = getattr(db, "rollback", None)
                if rollback is not None:
                    await rollback()
                log.bind(error_type=type(exc).__name__).warning(
                    "mtproto.profile.level_recalc_failed"
                )
            completeness = await read_profile_completeness(db, user_id=user_id)
            log.bind(country_code=inferred_country).info(
                "mtproto.profile.country_detected_from_language"
            )

    if completeness.country_code is None:
        prefs["profile_intake_pending"] = "country"
        await _write_profile_preferences(db, user_id=user_id, preferences=prefs)
        await db.commit()
        log.info("mtproto.profile.ask_country")
        return _profile_copy("country_question", text_value, PROFILE_COUNTRY_QUESTION)

    if completeness.age is None:
        prefs["profile_intake_pending"] = "age"
        await _write_profile_preferences(db, user_id=user_id, preferences=prefs)
        await db.commit()
        log.info("mtproto.profile.ask_age")
        return _profile_copy("age_question", text_value, PROFILE_AGE_QUESTION)

    return None


async def _persist_message(
    *,
    conv_id: str,
    sender_type: str,
    sender_id: str,
    content: str,
    model_name: str | None = None,
    message_id: str | None = None,
) -> str:
    msg_id = message_id or str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO messages "
                "(id, conversation_id, sender_type, sender_id, content, content_type, model_name, created_at) "
                "VALUES (:id, :cid, :sender_type, :sender_id, :content, 'text', :model_name, NOW())"
            ),
            {
                "id": msg_id,
                "cid": conv_id,
                "sender_type": sender_type,
                "sender_id": sender_id,
                "content": content,
                "model_name": model_name,
            },
        )
        await db.execute(
            text("UPDATE conversations SET last_message_at=NOW(), updated_at=NOW() WHERE id=:cid"),
            {"cid": conv_id},
        )
        await db.commit()
    return msg_id


async def handle_mtproto_new_message(client: Any, account_id: uuid.UUID, event: Any) -> None:
    """Handle one incoming real-user Telegram message end to end."""
    message = getattr(event, "message", event)
    if getattr(message, "out", False):
        return

    text_value = (
        getattr(message, "raw_text", None)
        or getattr(message, "text", None)
        or getattr(message, "message", None)
        or ""
    ).strip()
    if not text_value:
        logger.info("mtproto.inbound.skip_empty")
        return

    sender = await event.get_sender() if hasattr(event, "get_sender") else None
    sender_id = str(
        getattr(message, "sender_id", None)
        or getattr(event, "sender_id", None)
        or getattr(sender, "id", "")
    )
    if not sender_id:
        logger.warning("mtproto.inbound.missing_sender")
        return

    message_id = str(getattr(message, "id", "") or getattr(event, "id", "") or "")
    trace_id = _trace_id(message_id)
    external_id = f"tg_{sender_id}"
    nickname = getattr(sender, "first_name", None) or getattr(sender, "username", None)
    log = logger.bind(trace_id=trace_id, account_id=str(account_id), external_id=external_id)

    await _mark_read_after_delay(client, event, message, log)

    user_id, conv_id = await _get_or_create_user_and_conversation(
        external_id=external_id,
        nickname=nickname,
    )
    if not conv_id:
        log.bind(user_id=user_id).info("mtproto.inbound.user_reply_blocked")
        return
    log = log.bind(user_id=user_id, conv_id=conv_id, telegram_message_id=message_id)

    redis = await _get_redis()
    route_allowed = await ensure_mtproto_account_route_for_reply(
        redis,
        user_id=user_id,
        account_id=str(account_id),
    )
    if not route_allowed:
        pinned = None
        try:
            from services.mtproto.account_routing import get_mtproto_account_route

            pinned = await get_mtproto_account_route(redis, user_id=user_id)
        except Exception:
            pass
        log.bind(pinned_account_id=pinned).info("mtproto.inbound.route_skip")

    async with AsyncSessionLocal() as db:
        try:
            await upsert_telegram_peer_cache(
                db,
                user_id=user_id,
                conversation_id=conv_id,
                account_id=str(account_id),
                chat_id=int(sender_id),
                access_hash=getattr(sender, "access_hash", None),
                source="mtproto_inbound_message",
                trace_id=trace_id,
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            log.bind(error_type=type(exc).__name__).warning(
                "mtproto.peer_cache.upsert_failed"
            )
        try:
            await _persist_technical_country_hint(
                db,
                user_id=user_id,
                sender=sender,
                log=log,
            )
        except Exception as exc:
            await db.rollback()
            log.bind(error_type=type(exc).__name__).warning(
                "mtproto.profile.country_hint_failed"
            )

    user_msg_id = await _persist_message(
        conv_id=conv_id,
        sender_type="user",
        sender_id=user_id,
        content=text_value,
    )
    log.bind(message_id=user_msg_id).info("mtproto.inbound.persisted")

    # Keyword video requests must queue on whichever account received the message,
    # even when account routing skips LLM auto-reply on secondary MTProto accounts.
    await _try_queue_live_video_keyword_review(
        user_id=user_id,
        external_id=external_id,
        conv_id=conv_id,
        sender_id=sender_id,
        account_id=str(account_id),
        text_value=text_value,
        trace_id=trace_id,
        access_hash=getattr(sender, "access_hash", None),
        log=log,
    )

    if not route_allowed:
        return

    async with AsyncSessionLocal() as db:
        try:
            gate = await evaluate_human_takeover_gate(db, conv_id)
            await db.commit()
            if not gate.allows_auto_reply:
                log.bind(human_gate_reason=gate.reason).info(
                    "mtproto.inbound.human_takeover_blocked"
                )
                return
            if gate.released_to_ai:
                log.bind(human_gate_reason=gate.reason).info(
                    "mtproto.inbound.human_takeover_released"
                )
        except Exception as exc:
            await db.rollback()
            log.bind(error_type=type(exc).__name__).warning(
                "mtproto.inbound.human_takeover_gate_failed"
            )

    nurture_immediate_reply: str | None = None
    nurture_intent: str | None = None
    async with AsyncSessionLocal() as db:
        try:
            nurture_action = await handle_nurture_user_reply(
                db,
                user_id=user_id,
                external_user_id=external_id,
                conversation_id=conv_id,
                chat_id=int(sender_id),
                account_id=str(account_id),
                user_text=text_value,
                trace_id=trace_id,
                telegram_access_hash=getattr(sender, "access_hash", None),
            )
            await db.commit()
            nurture_immediate_reply = nurture_action.immediate_reply_text
            nurture_intent = nurture_action.intent
            log.bind(
                nurture_intent=nurture_action.intent,
                nurture_valid_reply=nurture_action.valid_reply,
                nurture_language=nurture_action.nurture_language,
            ).info("mtproto.nurture_reply.handled")
        except Exception as exc:
            await db.rollback()
            log.bind(error_type=type(exc).__name__).warning("mtproto.nurture_reply.failed")

    if nurture_intent == "spam":
        log.info("mtproto.inbound.spam_skip_reply")
        return

    _spawn_call_broadcast_enqueue(
        user_id=user_id,
        external_user_id=external_id,
        conversation_id=conv_id,
        chat_id=int(sender_id),
        account_id=str(account_id),
        user_text=text_value,
        trace_id=trace_id,
        telegram_access_hash=getattr(sender, "access_hash", None),
    )

    try:
        await _push_context(redis, conv_id, "user", text_value, user_msg_id)
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("mtproto.context.push_failed")
    _spawn_memory_write(
        user_id=user_id,
        conv_id=conv_id,
        msg_id=user_msg_id,
        content=text_value,
        trace_id=trace_id,
        redis=redis,
        log=log,
        source="inbound_user",
    )

    profile_followup: str | None = None
    async with AsyncSessionLocal() as db:
        try:
            profile_followup = await _handle_required_profile_intake(
                db,
                user_id=user_id,
                external_id=external_id,
                text_value=text_value,
                log=log,
            )
        except Exception as exc:
            await db.rollback()
            log.bind(error_type=type(exc).__name__).warning("mtproto.profile.intake_failed")

    async with AsyncSessionLocal() as db:
        try:
            reply_text = await generate_reply(
                user_id=user_id,
                conversation_id=conv_id,
                user_text=text_value,
                trace_id=trace_id,
                redis=redis,
                db=db,
                trigger_message_id=user_msg_id,
            )
        except LLMOrchestratorError as exc:
            log.bind(reason=str(exc)).warning("mtproto.orchestrator.failed")
            reply_text = "I am a little busy right now, talk in a bit?"
        if profile_followup and profile_followup not in reply_text:
            reply_text = f"{reply_text}\n\n{profile_followup}"
        if nurture_immediate_reply and nurture_immediate_reply not in reply_text:
            reply_text = f"{nurture_immediate_reply}\n\n{reply_text}"
        reply_text = sanitize_outbound_reply(reply_text, user_text=text_value)
        link_cooldown_active = await is_conversation_link_cooldown_active(
            db,
            conversation_id=conv_id,
        )
        app_download_decision = get_last_app_download_decision()
        if link_cooldown_active and not bypasses_link_cooldown(text_value):
            if not decision_bypasses_link_cooldown(app_download_decision):
                reply_text = strip_links_from_reply(reply_text)
                app_download_decision = None
        assistant_msg_id = str(uuid.uuid4())
        try:
            reply_text = await wrap_text_links_with_tracking(
                db,
                text_value=reply_text,
                base_url=str(settings.PUBLIC_BASE_URL).rstrip("/"),
                user_id=user_id,
                conversation_id=conv_id,
                message_id=assistant_msg_id,
                script_hit_id=(
                    app_download_decision.script_hit_id
                    if app_download_decision is not None
                    else None
                ),
                platform="telegram_real_user",
                sender_account_id=str(account_id),
                scene_step=(
                    app_download_decision.scene_step
                    if app_download_decision is not None
                    else None
                ),
                script_category=(
                    app_download_decision.category_key
                    if app_download_decision is not None
                    else None
                ),
                persona_slug=(
                    app_download_decision.persona_slug
                    if app_download_decision is not None
                    else None
                ),
                intent=(
                    app_download_decision.intent
                    if app_download_decision is not None
                    else None
                ),
                country_code=(
                    app_download_decision.country_code
                    if app_download_decision is not None
                    else None
                ),
                age=app_download_decision.age if app_download_decision is not None else None,
                user_level=(
                    app_download_decision.user_level
                    if app_download_decision is not None
                    else None
                ),
                is_t1_country=(
                    app_download_decision.is_t1_country
                    if app_download_decision is not None
                    else None
                ),
                metadata={"source": "mtproto_auto_reply", "trace_id": trace_id},
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            log.bind(error_type=type(exc).__name__).warning("mtproto.link_attribution_failed")

    async with AsyncSessionLocal() as db:
        if await should_skip_duplicate_outbound(
            db,
            user_id=user_id,
            content=reply_text,
            trace_id=trace_id,
            source="mtproto_auto_reply",
        ):
            return

    peer = getattr(event, "chat_id", None) or sender_id
    telegram_reply_text = render_tracking_links_as_html_cta(reply_text)
    send_kwargs = {"parse_mode": "html"} if telegram_reply_text != reply_text else {}
    sent = await send_human_like_message(
        client,
        peer,
        telegram_reply_text,
        policy=_reply_delay_policy(reply_text),
        **send_kwargs,
    )
    sent_id = str(getattr(sent, "id", "") or "")
    assistant_msg_id = await _persist_message(
        conv_id=conv_id,
        sender_type="assistant",
        sender_id=str(account_id),
        content=reply_text,
        model_name=getattr(settings, "OPENROUTER_MODEL", None),
        message_id=assistant_msg_id,
    )
    _spawn_memory_write(
        user_id=user_id,
        conv_id=conv_id,
        msg_id=assistant_msg_id,
        content=reply_text,
        trace_id=trace_id,
        redis=redis,
        log=log,
        source="outbound_assistant",
    )
    nurture_source = (
        "asset_keyword"
        if app_download_decision is not None
        and getattr(app_download_decision, "intent", None) == "asset_keyword_request"
        else "reply"
    )
    async with AsyncSessionLocal() as db:
        try:
            await schedule_nurture_after_reply(
                db,
                user_id=user_id,
                external_user_id=external_id,
                conversation_id=conv_id,
                chat_id=int(sender_id),
                assistant_message_id=assistant_msg_id,
                trace_id=trace_id,
                account_id=str(account_id),
                telegram_access_hash=getattr(sender, "access_hash", None),
                source=nurture_source,
            )
        except Exception as exc:
            await db.rollback()
            log.bind(error_type=type(exc).__name__).warning(
                "mtproto.app_download_nurture.schedule_failed"
            )
    if app_download_decision is not None:
        for asset in app_download_decision.assets:
            asset_content = str(asset.get("asset_url") or "")
            async with AsyncSessionLocal() as db:
                if await should_skip_duplicate_outbound(
                    db,
                    user_id=user_id,
                    content=asset_content,
                    trace_id=trace_id,
                    source="mtproto_auto_reply_asset",
                ):
                    continue
            media_sent = await send_mtproto_asset(
                client,
                peer,
                asset,
                trace_id=trace_id,
            )
            if media_sent is not None:
                await _persist_message(
                    conv_id=conv_id,
                    sender_type="assistant",
                    sender_id=str(account_id),
                    content=str(asset.get("asset_url") or ""),
                    model_name=getattr(settings, "OPENROUTER_MODEL", None),
                )
    try:
        await _push_context(redis, conv_id, "assistant", reply_text, assistant_msg_id)
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("mtproto.reply.ctx_push_failed")
    log.bind(message_id=assistant_msg_id, telegram_sent_id=sent_id).info("mtproto.reply.sent")


async def _try_queue_live_video_keyword_review(
    *,
    user_id: str,
    external_id: str,
    conv_id: str,
    sender_id: str,
    account_id: str,
    text_value: str,
    trace_id: str,
    access_hash: int | None,
    log: Any,
) -> str | None:
    try:
        async with AsyncSessionLocal() as db:
            try:
                video_job_id = await maybe_queue_live_video_call_operator_review(
                    db,
                    user_id=user_id,
                    external_user_id=external_id,
                    conversation_id=conv_id,
                    chat_id=int(sender_id),
                    account_id=account_id,
                    user_text=text_value,
                    trace_id=trace_id,
                    telegram_access_hash=access_hash,
                )
                if video_job_id:
                    log.bind(job_id=video_job_id).info(
                        "mtproto.video_request_handoff.keyword_review_queued"
                    )
                return video_job_id
            except Exception:
                await db.rollback()
                raise
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning(
            "mtproto.video_request_handoff.failed"
        )
        return None


def _spawn_call_broadcast_enqueue(
    *,
    user_id: str,
    external_user_id: str | None,
    conversation_id: str | None,
    chat_id: int,
    account_id: str,
    user_text: str | None,
    trace_id: str | None,
    telegram_access_hash: int | None = None,
) -> None:
    """Fire-and-forget video call queueing; no-op unless CALL_BROADCAST_ENABLED."""
    if not getattr(settings, "CALL_BROADCAST_ENABLED", False):
        return

    from services.call_broadcast.triggers import maybe_enqueue_call_broadcast

    asyncio.create_task(
        maybe_enqueue_call_broadcast(
            user_id=user_id,
            external_user_id=external_user_id,
            conversation_id=conversation_id,
            chat_id=chat_id,
            account_id=account_id,
            user_text=user_text,
            trace_id=trace_id,
            telegram_access_hash=telegram_access_hash,
        )
    )
