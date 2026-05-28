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
from services.app_download_conversion import get_last_app_download_decision
from services.link_attribution import wrap_text_links_with_tracking
from services.emotion_lexicon import detect_language_from_text, normalize_language
from services.profile_intake import (
    country_from_locale,
    country_from_text_language,
    extract_age_from_text,
    normalize_country_code,
    read_profile_completeness,
    write_age,
    write_country_code,
)
from services.script_asset_delivery import send_mtproto_asset
from services.app_download_nurture import schedule_download_followups_after_reply
from services.content_safety import evaluate_inbound_content_safety
from services.user_level_service import user_level_service
from services.mtproto.account_routing import pin_mtproto_account_route
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
PROFILE_AGE_RETRY = "Please reply with your age as a number, for example 24."

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

        conv_row = (
            await db.execute(
                text(
                    "SELECT id FROM conversations "
                    "WHERE user_id=:uid AND state NOT IN ('CLOSED','ESCALATED') "
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


async def _write_profile_preferences(db: Any, *, user_id: str, preferences: dict[str, Any]) -> None:
    await db.execute(
        text(
            """
            UPDATE user_profiles
            SET preferences = CAST(:prefs AS jsonb), updated_at = NOW()
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
    prefs = await _profile_preferences(db, user_id=user_id)
    pending = str(prefs.get("profile_intake_pending") or "").strip()
    completeness = await read_profile_completeness(db, user_id=user_id)

    if pending == "country":
        country_code = normalize_country_code(text_value)
        if not country_code:
            log.info("mtproto.profile.country_still_missing")
            return _profile_copy("country_retry", text_value, PROFILE_COUNTRY_RETRY)
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
        inferred_country = country_from_text_language(text_value)
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
    log = log.bind(user_id=user_id, conv_id=conv_id, telegram_message_id=message_id)

    redis = await _get_redis()
    try:
        await pin_mtproto_account_route(
            redis,
            user_id=user_id,
            account_id=str(account_id),
        )
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("mtproto.route.pin_failed")

    async with AsyncSessionLocal() as db:
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

    if settings.CONTENT_SAFETY_ENABLED:
        safety_result = await evaluate_inbound_content_safety(text_value, trace_id=trace_id)
        if safety_result.get("blocked"):
            refusal = "这个话题我没办法聊，换个方向说说？"
            peer = getattr(event, "chat_id", None) or sender_id
            await send_human_like_message(
                client,
                peer,
                refusal,
                policy=_reply_delay_policy(refusal),
            )
            await _persist_message(
                conv_id=conv_id,
                sender_type="assistant",
                sender_id=str(account_id),
                content=refusal,
                model_name=getattr(settings, "OPENROUTER_MODEL", None),
            )
            log.bind(
                block_reason=safety_result.get("block_reason"),
            ).info("mtproto.content_safety.blocked")
            return

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
        app_download_decision = get_last_app_download_decision()
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

    peer = getattr(event, "chat_id", None) or sender_id
    sent = await send_human_like_message(
        client,
        peer,
        reply_text,
        policy=_reply_delay_policy(reply_text),
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
    async with AsyncSessionLocal() as db:
        try:
            await schedule_download_followups_after_reply(
                db,
                user_id=user_id,
                external_user_id=external_id,
                conversation_id=conv_id,
                chat_id=int(sender_id),
                assistant_message_id=assistant_msg_id,
                trace_id=trace_id,
                account_id=str(account_id),
            )
        except Exception as exc:
            await db.rollback()
            log.bind(error_type=type(exc).__name__).warning(
                "mtproto.app_download_nurture.schedule_failed"
            )
    if app_download_decision is not None:
        for asset in app_download_decision.assets:
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
