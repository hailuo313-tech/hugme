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
from services.ai_message_limit import (
    AIMessageLimitReached,
    T1_COUNTRY_ASK_WINDOW,
    inspect_ai_message_quota,
    maybe_handoff_t1_after_ai_cap,
)
from services.app_download_conversion import (
    decision_bypasses_link_cooldown,
    get_last_app_download_decision,
    is_t1_sixth_message_decision,
)
from services.link_cooldown import is_conversation_link_cooldown_active, strip_links_from_reply
from services.link_attribution import render_tracking_links_as_html_cta, wrap_text_links_with_tracking
from services.emotion_lexicon import detect_language_from_text, normalize_language
from services.profile_intake import (
    city_country_from_text,
    clear_profile_intake_pending,
    country_from_recent_user_messages,
    country_from_locale,
    extract_age_from_text,
    normalize_country_code,
    read_profile_completeness,
    record_stated_location_from_text,
    write_age,
    write_country_code,
    write_city_country,
)
from services.reply_sanitize import (
    nurture_boilerplate_conflicts_with_llm_reply,
    sanitize_outbound_reply,
)
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
from services.inbound_reply_coalescer import (
    finalize_coalesced_inbound_turn,
    inbound_reply_turn_stale,
    register_inbound_turn,
    release_inbound_reply_lock,
    try_acquire_inbound_reply_lock,
)
from services.mtproto.account_routing import ensure_mtproto_account_route_for_reply
from services.mtproto.peer_phone_country import (
    fetch_peer_phone_country,
    should_refresh_phone_country,
)
from services.mtproto.inbound_text import inbound_text_for_reply
from services.message_repeat_guard import should_skip_duplicate_outbound
from services.mtproto.human_like_send import HumanLikeSendPolicy, send_human_like_message
from services.product_i18n import profile_intake_text


CONTEXT_MAX_MESSAGES = 200
CONTEXT_TTL_SECONDS = 86400 * 3
INBOUND_READ_ACK_DELAY_SECONDS = 4.0
PROFILE_COUNTRY_QUESTION = (
    "Before we continue, which city are you in? I'll use it to identify your country."
)
PROFILE_COUNTRY_RETRY = (
    "I couldn't identify that city. Which city are you in?"
)
PROFILE_COUNTRY_MEDIA_QUESTION = (
    "I got your photo or sticker. Before we continue, which city are you in? "
    "I'll use it to identify your country."
)
PROFILE_COUNTRY_MAX_PROMPTS = 3
PROFILE_COUNTRY_WEAK_SOURCES = frozenset({"language_fallback", "telegram_language_code"})
PROFILE_AGE_QUESTION = "Thanks. How old are you?"
PROFILE_AGE_RETRY = "Lmao you completely ignored my question! How old are you anyway? Tell me a number so I know if you're a big boy or just a baby. 😜"


async def _get_account_reply_mode(account_id: uuid.UUID) -> str:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text(
                """
                SELECT COALESCE(metadata->>'reply_mode', 'ai') AS reply_mode
                  FROM telegram_accounts
                 WHERE id = :account_id
                """
            ),
            {"account_id": str(account_id)},
        )
        value = result.scalar_one_or_none()
    return "fixed" if value == "fixed" else "ai"


def _profile_copy(kind: str, text_value: str, fallback: str) -> str:
    return profile_intake_text(kind, None, user_text=text_value) or fallback

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



async def _ensure_first_reply_app_link(
    db,
    *,
    conversation_id: str,
    user_id: str,
    reply_text: str,
    user_text: str,
    trigger_message_id: str | None,
    trace_id: str,
    account_id: str | None = None,
) -> str:
    return reply_text


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
    client: Any = None,
) -> None:
    completeness = await read_profile_completeness(db, user_id=user_id)
    prefs = await _profile_preferences(db, user_id=user_id)
    already_fetched = bool(
        prefs.get("telegram_phone_country_fetched")
        or normalize_country_code(prefs.get("telegram_phone_country"))
    )
    need_phone_country = should_refresh_phone_country(
        existing_country_code=completeness.country_code,
        country_source=str(prefs.get("country_source") or ""),
        already_fetched=already_fetched,
    )
    if need_phone_country and client is not None and sender is not None:
        try:
            peer_country = await fetch_peer_phone_country(client, sender)
            extra: dict[str, Any] = {"telegram_phone_country_fetched": True}
            if peer_country.registration_month:
                extra["telegram_registration_month"] = peer_country.registration_month
            if peer_country.raw_phone_country:
                extra["telegram_phone_country"] = peer_country.raw_phone_country
            await _write_profile_preferences(db, user_id=user_id, preferences=extra)
            if peer_country.country_code:
                await write_country_code(
                    db,
                    user_id=user_id,
                    country_code=peer_country.country_code,
                    source="telegram_phone_country",
                )
                await db.commit()
                log.bind(
                    country_code=peer_country.country_code,
                    registration_month=peer_country.registration_month,
                ).info("mtproto.profile.phone_country_detected")
                return
            await db.commit()
        except Exception as exc:
            rollback = getattr(db, "rollback", None)
            if rollback is not None:
                await rollback()
            log.bind(error_type=type(exc).__name__).warning(
                "mtproto.profile.phone_country_lookup_failed"
            )
            completeness = await read_profile_completeness(db, user_id=user_id)

    if completeness.country_code:
        return
    code = country_from_locale(
        getattr(sender, "lang_code", None)
        or getattr(sender, "language_code", None)
        or getattr(sender, "lang", None)
    )
    if not code:
        return
    await write_country_code(
        db,
        user_id=user_id,
        country_code=code,
        source="telegram_language_code",
    )
    await db.commit()
    log.bind(country_code=code).info("mtproto.profile.country_detected")


def _keep_asking_country(*, country_prompt_count: int, ai_system_sent_count: int | None) -> bool:
    if ai_system_sent_count is not None and ai_system_sent_count < T1_COUNTRY_ASK_WINDOW:
        return True
    return country_prompt_count < PROFILE_COUNTRY_MAX_PROMPTS


async def _handle_required_profile_intake(
    db: Any,
    *,
    user_id: str,
    external_id: str,
    text_value: str,
    log: Any,
    ai_system_sent_count: int | None = None,
) -> str | None:
    """Persist profile answers when present and return a non-blocking follow-up question."""
    await _ensure_user_profile_row(db, user_id=user_id)
    prefs = await _profile_preferences(db, user_id=user_id)
    pending = str(prefs.get("profile_intake_pending") or "").strip()
    completeness = await read_profile_completeness(db, user_id=user_id)
    country_source = str(prefs.get("country_source") or "").strip()
    country_known = bool(completeness.country_code) and country_source not in PROFILE_COUNTRY_WEAK_SOURCES
    try:
        country_prompt_count = max(0, int(prefs.get("profile_country_prompt_count") or 0))
    except (TypeError, ValueError):
        country_prompt_count = 0

    if pending != "country":
        try:
            recorded = await record_stated_location_from_text(
                db,
                user_id=user_id,
                text_value=text_value,
            )
            if recorded:
                await db.commit()
                completeness = await read_profile_completeness(db, user_id=user_id)
        except Exception as exc:
            rollback = getattr(db, "rollback", None)
            if rollback is not None:
                await rollback()
            log.bind(error_type=type(exc).__name__).warning(
                "mtproto.profile.stated_location_failed"
            )
            completeness = await read_profile_completeness(db, user_id=user_id)

    if pending == "country" and country_known:
        await clear_profile_intake_pending(db, user_id=user_id)
        prefs.pop("profile_intake_pending", None)
        prefs.pop("profile_country_prompt_exhausted", None)
        if completeness.age is None:
            prefs["profile_intake_pending"] = "age"
            await _write_profile_preferences(db, user_id=user_id, preferences=prefs)
            await db.commit()
            log.info("mtproto.profile.country_already_known_ask_age")
            return _profile_copy("age_question", text_value, PROFILE_AGE_QUESTION)
        await db.commit()
        log.info("mtproto.profile.country_already_known")
        return None

    if pending == "country":
        city, country_code = city_country_from_text(text_value)
        country_code = country_code or normalize_country_code(text_value)
        if not country_code:
            country_code = await country_from_recent_user_messages(
                db,
                user_id=user_id,
            )
        if not country_code:
            if not _keep_asking_country(
                country_prompt_count=country_prompt_count,
                ai_system_sent_count=ai_system_sent_count,
            ):
                prefs.pop("profile_intake_pending", None)
                prefs["profile_country_prompt_exhausted"] = True
                await _write_profile_preferences(db, user_id=user_id, preferences=prefs)
                await db.commit()
                log.bind(prompt_count=country_prompt_count).info(
                    "mtproto.profile.country_prompt_limit_reached"
                )
                return None
            prefs["profile_country_prompt_count"] = country_prompt_count + 1
            await _write_profile_preferences(db, user_id=user_id, preferences=prefs)
            await db.commit()
            log.info("mtproto.profile.city_still_missing")
            if text_value in {"[media]", "[photo]", "[sticker]"}:
                return _profile_copy(
                    "country_question", text_value, PROFILE_COUNTRY_MEDIA_QUESTION
                )
            return _profile_copy("country_retry", text_value, PROFILE_COUNTRY_RETRY)
        if city:
            await write_city_country(db, user_id=user_id, city=city, country_code=country_code)
        else:
            await write_country_code(
                db,
                user_id=user_id,
                country_code=country_code,
                source="chat_answer",
            )
        prefs["profile_intake_pending"] = "age"
        prefs.pop("profile_country_prompt_exhausted", None)
        await _write_profile_preferences(db, user_id=user_id, preferences=prefs)
        await db.commit()
        completeness_after = await read_profile_completeness(db, user_id=user_id)
        try:
            await user_level_service.calculate_and_persist_user_level(
                db,
                user_id=user_id,
                external_user_id=external_id,
                country_code=completeness_after.country_code or country_code,
            )
            await db.commit()
        except Exception as exc:
            rollback = getattr(db, "rollback", None)
            if rollback is not None:
                await rollback()
            log.bind(error_type=type(exc).__name__).warning(
                "mtproto.profile.level_recalc_failed"
            )
        log.bind(city=city, country_code=country_code).info("mtproto.profile.country_collected")
        return _profile_copy("age_question", text_value, PROFILE_AGE_QUESTION)

    if pending == "age":
        if completeness.age is not None:
            prefs.pop("profile_intake_pending", None)
            await clear_profile_intake_pending(db, user_id=user_id)
            await db.commit()
            log.bind(age=completeness.age).info("mtproto.profile.age_already_known")
            return None
        age = extract_age_from_text(text_value)
        if age is None:
            log.info("mtproto.profile.age_still_missing")
            return _profile_copy("age_retry", text_value, PROFILE_AGE_RETRY)
        await write_age(db, user_id=user_id, age=age, source="chat_answer")
        prefs.pop("profile_intake_pending", None)
        await clear_profile_intake_pending(db, user_id=user_id)
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

    if not country_known:
        inferred_country = (
            normalize_country_code(text_value)
            or await country_from_recent_user_messages(db, user_id=user_id)
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
            country_known = False
            log.bind(country_code=inferred_country).info(
                "mtproto.profile.country_detected_from_message"
            )

    if not country_known and _keep_asking_country(
        country_prompt_count=country_prompt_count,
        ai_system_sent_count=ai_system_sent_count,
    ):
        prefs["profile_intake_pending"] = "country"
        prefs["profile_country_prompt_count"] = country_prompt_count + 1
        await _write_profile_preferences(db, user_id=user_id, preferences=prefs)
        await db.commit()
        log.info("mtproto.profile.ask_country")
        if text_value in {"[media]", "[photo]", "[sticker]"}:
            return _profile_copy(
                "country_question", text_value, PROFILE_COUNTRY_MEDIA_QUESTION
            )
        return _profile_copy("country_question", text_value, PROFILE_COUNTRY_QUESTION)

    if not country_known:
        prefs.pop("profile_intake_pending", None)
        prefs["profile_country_prompt_exhausted"] = True
        await _write_profile_preferences(db, user_id=user_id, preferences=prefs)
        await db.commit()
        log.bind(prompt_count=country_prompt_count).info(
            "mtproto.profile.country_prompt_limit_reached"
        )
        return None

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
    telegram_account_id: str | None = None,
    content_type: str = "text",
) -> str:
    msg_id = message_id or str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO messages "
                "(id, conversation_id, sender_type, sender_id, content, content_type, model_name, "
                "telegram_account_id, created_at) "
                "VALUES (:id, :cid, :sender_type, :sender_id, :content, :content_type, :model_name, "
                "CAST(:telegram_account_id AS uuid), NOW())"
            ),
            {
                "id": msg_id,
                "cid": conv_id,
                "sender_type": sender_type,
                "sender_id": sender_id,
                "content": content,
                "content_type": content_type or "text",
                "model_name": model_name,
                "telegram_account_id": telegram_account_id,
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
    from services.runtime_ownership import this_process_may_hold_telegram_session

    if not await this_process_may_hold_telegram_session(str(account_id)):
        logger.bind(account_id=str(account_id)).info("mtproto.inbound.skip_runtime_owned")
        return
    message = getattr(event, "message", event)
    if getattr(message, "out", False):
        return
    # A Telegram account may be present in busy groups/channels.  Those updates
    # are not people entering this account's one-to-one inbox and must never be
    # turned into CRM users or counted as new users.
    if getattr(event, "is_private", None) is False:
        logger.bind(account_id=str(account_id)).info("mtproto.inbound.skip_non_private")
        return

    from services.call_broadcast.post_inbound_video_fixed_messages import (
        handle_post_video_fixed_user_reply,
        is_inbound_screenshot,
        is_post_video_fixed_03_stopped,
    )

    is_screenshot = is_inbound_screenshot(message)
    text_value = inbound_text_for_reply(message)
    if not text_value and is_screenshot:
        text_value = "[photo]"
    if not text_value:
        # A valid private inbound turn must not be dropped just because
        # Telethon did not expose text for its media/service variant.
        text_value = "[media]"
        logger.info("mtproto.inbound.empty_recovered_as_media")

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
    migration_linked = False
    async with AsyncSessionLocal() as db:
        try:
            from services.telegram_user_migration import mark_inbound_migration_reply

            migration_linked = await mark_inbound_migration_reply(
                db,
                account_id=str(account_id),
                chat_id=int(sender_id),
                user_id=user_id,
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            log.bind(error_type=type(exc).__name__).warning(
                "mtproto.inbound.migration_link_failed"
            )
    if migration_linked:
        from services.mtproto.account_routing import pin_mtproto_account_route

        await pin_mtproto_account_route(
            redis, user_id=user_id, account_id=str(account_id)
        )
    async with AsyncSessionLocal() as db:
        try:
            from services.video_reinvite import mark_video_reinvite_reply

            await mark_video_reinvite_reply(
                db,
                user_id=user_id,
                account_id=str(account_id),
                chat_id=int(sender_id),
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            log.bind(error_type=type(exc).__name__).warning(
                "mtproto.inbound.video_reinvite_reply_mark_failed"
            )
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
                peer_metadata={
                    key: value
                    for key, value in {
                        "phone": getattr(sender, "phone", None),
                        "username": getattr(sender, "username", None),
                        "telegram_user_id": getattr(sender, "id", None),
                    }.items()
                    if value not in (None, "")
                },
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
                client=client,
                log=log,
            )
        except Exception as exc:
            await db.rollback()
            log.bind(error_type=type(exc).__name__).warning(
                "mtproto.profile.country_hint_failed"
            )

    user_msg_id = str(uuid.uuid4())
    content_type = "text"
    from services.mtproto.inbound_media import (
        inbound_av_media_kind,
        inbound_image_media_kind,
        save_inbound_telegram_av,
        save_inbound_telegram_photo,
    )

    if inbound_image_media_kind(message):

        saved = await save_inbound_telegram_photo(
            client, message, message_id=user_msg_id
        )
        content_type = "image"
        if not text_value or text_value == "[media]":
            text_value = "[image]"
        if saved is None:
            log.warning("mtproto.inbound.photo_save_failed")
    else:
        av_kind = inbound_av_media_kind(message)
        if av_kind:
            saved = await save_inbound_telegram_av(
                client, message, message_id=user_msg_id, kind=av_kind
            )
            content_type = av_kind
            if not text_value or text_value == "[media]":
                text_value = "[video]" if av_kind == "video" else "[audio]"
            if saved is None:
                log.bind(kind=av_kind).warning("mtproto.inbound.av_save_failed")
    if text_value == "[media]" and content_type == "text":
        # Unknown attachments and service events are not playable images.
        # Preserve the event without creating a bogus media URL in admin.
        text_value = (
            "[unsupported attachment]"
            if getattr(message, "media", None) is not None
            else "[service event]"
        )
    user_msg_id = await _persist_message(
        conv_id=conv_id,
        sender_type="user",
        sender_id=user_id,
        content=text_value,
        telegram_account_id=str(account_id),
        message_id=user_msg_id,
        content_type=content_type,
    )
    log.bind(message_id=user_msg_id, content_type=content_type).info("mtproto.inbound.persisted")

    async with AsyncSessionLocal() as db:
        try:
            stopped = await handle_post_video_fixed_user_reply(
                db,
                conversation_id=conv_id,
                text_value=text_value,
                is_screenshot=is_screenshot,
                trace_id=trace_id,
                message_id=user_msg_id,
            )
            if not stopped:
                stopped = await is_post_video_fixed_03_stopped(
                    db, conversation_id=conv_id
                )
            if stopped:
                log.info("mtproto.inbound.post_video_fixed_stopped")
                return
        except Exception as exc:
            await db.rollback()
            log.bind(error_type=type(exc).__name__).warning(
                "mtproto.inbound.post_video_fixed_stop_failed"
            )

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
            return

    try:
        reply_mode = await _get_account_reply_mode(account_id)
    except Exception as exc:
        reply_mode = "ai"
        log.bind(error_type=type(exc).__name__).warning(
            "mtproto.inbound.reply_mode_check_failed"
        )
    if reply_mode == "fixed":
        enqueued = 0
        async with AsyncSessionLocal() as db:
            try:
                from services.fixed_auto_reply_service import (
                    enqueue_jobs_for_fixed_mode_inbound,
                )
                from services.fixed_campaign_interest import (
                    evaluate_fixed_campaign_interest,
                )

                enqueued = await enqueue_jobs_for_fixed_mode_inbound(
                    db,
                    user_id=user_id,
                    conversation_id=conv_id,
                    external_user_id=external_id,
                    account_id=str(account_id),
                    chat_id=int(sender_id),
                    telegram_access_hash=getattr(sender, "access_hash", None),
                )
                interested = await evaluate_fixed_campaign_interest(
                    db,
                    user_id=user_id,
                    conversation_id=conv_id,
                    user_text=text_value,
                    trace_id=trace_id,
                )
                await db.commit()
                log.bind(fixed_auto_reply_jobs=enqueued, interested=interested).info(
                    "mtproto.inbound.fixed_reply_mode_queued"
                )
            except Exception as exc:
                await db.rollback()
                log.bind(error_type=type(exc).__name__).warning(
                    "mtproto.inbound.fixed_reply_mode_queue_failed"
                )
        # Fixed campaign mode never falls through to ordinary AI chat. Existing
        # users remain silent; eligible new users receive the configured sequence.
        if enqueued <= 0:
            log.info("mtproto.inbound.fixed_campaign_no_new_jobs")
        return

    async with AsyncSessionLocal() as db:
        try:
            from services.post_inbound_video_expert_gate import (
                block_post_inbound_video_auto_reply,
            )

            if await block_post_inbound_video_auto_reply(
                db,
                user_id=user_id,
                conversation_id=conv_id,
                chat_id=int(sender_id),
                trace_id=trace_id,
            ):
                log.info("mtproto.inbound.post_inbound_video_expert_blocked")
                return
        except Exception as exc:
            await db.rollback()
            log.bind(error_type=type(exc).__name__).warning(
                "mtproto.inbound.post_inbound_video_expert_gate_failed"
            )

    coalesce_registration = None
    if route_allowed:
        try:
            coalesce_registration = await register_inbound_turn(
                redis,
                conversation_id=conv_id,
                message_id=user_msg_id,
                text_value=text_value,
                trace_id=trace_id,
            )
        except Exception as exc:
            log.bind(error_type=type(exc).__name__).warning(
                "mtproto.inbound.coalesce_register_failed"
            )

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
            coalesced = await finalize_coalesced_inbound_turn(
                redis,
                db,
                conversation_id=conv_id,
                message_id=user_msg_id,
                text_value=text_value,
                trace_id=trace_id,
                registration=coalesce_registration,
                sleep=asyncio.sleep,
            )
        except Exception as exc:
            await db.rollback()
            log.bind(error_type=type(exc).__name__).warning(
                "mtproto.inbound.coalesce_failed"
            )
            coalesced = None

    if coalesced is not None and not coalesced.should_reply:
        log.bind(
            coalesced_message_count=coalesced.message_count,
            coalesced_trigger_message_id=coalesced.trigger_message_id,
        ).info("mtproto.inbound.coalesced_skip_duplicate_reply")
        return

    reply_user_text = coalesced.merged_text if coalesced is not None else text_value
    reply_trigger_message_id = (
        coalesced.trigger_message_id if coalesced is not None else user_msg_id
    )
    claimed_message_ids = (
        coalesced.message_ids if coalesced is not None else (user_msg_id,)
    )
    if not await try_acquire_inbound_reply_lock(
        redis,
        conversation_id=conv_id,
        owner_message_id=reply_trigger_message_id,
    ):
        log.bind(trigger_message_id=reply_trigger_message_id).info(
            "mtproto.inbound.reply_lock_busy"
        )
        return

    try:
        await _deliver_mtproto_inbound_reply(
            client=client,
            account_id=account_id,
            event=event,
            sender=sender,
            sender_id=sender_id,
            user_id=user_id,
            conv_id=conv_id,
            external_id=external_id,
            text_value=text_value,
            reply_user_text=reply_user_text,
            reply_trigger_message_id=reply_trigger_message_id,
            claimed_message_ids=claimed_message_ids,
            coalesced=coalesced,
            redis=redis,
            trace_id=trace_id,
            log=log,
        )
    finally:
        await release_inbound_reply_lock(
            redis,
            conversation_id=conv_id,
            owner_message_id=reply_trigger_message_id,
        )


async def _deliver_mtproto_inbound_reply(
    *,
    client: Any,
    account_id: uuid.UUID,
    event: Any,
    sender: Any,
    sender_id: str,
    user_id: str,
    conv_id: str,
    external_id: str,
    text_value: str,
    reply_user_text: str,
    reply_trigger_message_id: str,
    claimed_message_ids: tuple[str, ...],
    coalesced: Any,
    redis: Any,
    trace_id: str,
    log: Any,
) -> None:
    if coalesced is not None and coalesced.message_count > 1:
        trace_id = coalesced.trace_id
        log = log.bind(
            trace_id=trace_id,
            coalesced_message_count=coalesced.message_count,
            coalesced_trigger_message_id=reply_trigger_message_id,
        )
        log.info("mtproto.inbound.coalesced_reply")

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
                user_text=reply_user_text,
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

    from services.product_i18n import (
        inbound_call_redirect_reply,
        is_inbound_call_help_request,
    )
    from services.video_request_handoff import requires_operator_video_handoff

    if nurture_intent == "outbound_call_redirect" and nurture_immediate_reply:
        outbound_only_reply = nurture_immediate_reply
    elif requires_operator_video_handoff(reply_user_text):
        outbound_only_reply = nurture_immediate_reply or inbound_call_redirect_reply(reply_user_text)
    elif is_inbound_call_help_request(reply_user_text):
        outbound_only_reply = nurture_immediate_reply or inbound_call_redirect_reply(reply_user_text)
    else:
        outbound_only_reply = None

    _spawn_call_broadcast_enqueue(
        user_id=user_id,
        external_user_id=external_id,
        conversation_id=conv_id,
        chat_id=int(sender_id),
        account_id=str(account_id),
        user_text=reply_user_text,
        trace_id=trace_id,
        telegram_access_hash=getattr(sender, "access_hash", None),
    )

    try:
        await _push_context(redis, conv_id, "user", text_value, reply_trigger_message_id)
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("mtproto.context.push_failed")
    _spawn_memory_write(
        user_id=user_id,
        conv_id=conv_id,
        msg_id=reply_trigger_message_id,
        content=text_value,
        trace_id=trace_id,
        redis=redis,
        log=log,
        source="inbound_user",
    )

    profile_followup: str | None = None
    async with AsyncSessionLocal() as db:
        try:
            quota = await inspect_ai_message_quota(db, user_id=user_id)
            profile_followup = await _handle_required_profile_intake(
                db,
                user_id=user_id,
                external_id=external_id,
                text_value=reply_user_text,
                log=log,
                ai_system_sent_count=quota.system_sent_count,
            )
        except Exception as exc:
            await db.rollback()
            log.bind(error_type=type(exc).__name__).warning("mtproto.profile.intake_failed")

    profile_intake_only = False
    async with AsyncSessionLocal() as db:
        try:
            handed = await maybe_handoff_t1_after_ai_cap(
                db,
                user_id=user_id,
                conversation_id=conv_id,
                trace_id=trace_id,
            )
            if handed:
                await db.commit()
                log.info("mtproto.t1_handoff.before_generate")
                return
            if outbound_only_reply:
                reply_text = outbound_only_reply
            else:
                reply_text = await generate_reply(
                    user_id=user_id,
                    conversation_id=conv_id,
                    user_text=reply_user_text,
                    trace_id=trace_id,
                    redis=redis,
                    db=db,
                    trigger_message_id=reply_trigger_message_id,
                )
        except AIMessageLimitReached as exc:
            log.bind(reason=str(exc), is_t1=getattr(exc, "is_t1", False)).info("mtproto.reply.ai_limit")
            if getattr(exc, "is_t1", False):
                try:
                    handed = await maybe_handoff_t1_after_ai_cap(
                        db,
                        user_id=user_id,
                        conversation_id=conv_id,
                        trace_id=trace_id,
                    )
                    if handed:
                        await db.commit()
                except Exception as handoff_exc:
                    await db.rollback()
                    log.bind(error_type=type(handoff_exc).__name__).warning(
                        "mtproto.t1_ai_cap.handoff_failed"
                    )
                return
            if not profile_followup:
                return
            reply_text = profile_followup
            profile_intake_only = True
        except LLMOrchestratorError as exc:
            log.bind(reason=str(exc)).warning("mtproto.orchestrator.failed")
            reply_text = "I am a little busy right now, talk in a bit?"
        except Exception as exc:
            # The inbound message is already persisted. Never leave the user
            # unanswered because profile/context DB work or a model adapter
            # raised an unexpected exception.
            await db.rollback()
            log.bind(
                error_type=type(exc).__name__,
                reason=str(exc)[:300],
            ).warning("mtproto.orchestrator.unexpected_fallback")
            reply_text = "I am a little busy right now, talk in a bit?"
        if (
            profile_followup
            and profile_followup not in reply_text
            and not is_t1_sixth_message_decision(get_last_app_download_decision())
        ):
            reply_text = f"{reply_text}\n\n{profile_followup}"
        if nurture_immediate_reply:
            async with AsyncSessionLocal() as db:
                if await should_skip_duplicate_outbound(
                    db,
                    user_id=user_id,
                    content=nurture_immediate_reply,
                    trace_id=trace_id,
                    source="mtproto_nurture_boilerplate",
                    redis=redis,
                ):
                    nurture_immediate_reply = None
        if nurture_immediate_reply and nurture_boilerplate_conflicts_with_llm_reply(
            nurture_immediate_reply,
            reply_text,
        ):
            log.info("mtproto.nurture_reply.skipped_call_conflict")
            nurture_immediate_reply = None
        if nurture_immediate_reply and nurture_immediate_reply not in reply_text:
            reply_text = f"{nurture_immediate_reply}\n\n{reply_text}"
        reply_text = sanitize_outbound_reply(reply_text, user_text=reply_user_text)
        link_cooldown_active = await is_conversation_link_cooldown_active(
            db,
            conversation_id=conv_id,
        )
        app_download_decision = get_last_app_download_decision()
        if link_cooldown_active and not bypasses_link_cooldown(reply_user_text):
            if not decision_bypasses_link_cooldown(app_download_decision):
                reply_text = strip_links_from_reply(reply_text)
                app_download_decision = None
        assistant_msg_id = str(uuid.uuid4())
        try:
            reply_text = await _ensure_first_reply_app_link(
                db,
                conversation_id=conv_id,
                user_id=user_id,
                reply_text=reply_text,
                user_text=reply_user_text,
                trigger_message_id=reply_trigger_message_id,
                trace_id=trace_id,
                account_id=str(account_id),
            )
            app_download_decision = get_last_app_download_decision()
        except Exception as exc:
            log.bind(error_type=type(exc).__name__).warning(
                "mtproto.first_reply_app_link.failed"
            )
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

    asset_keyword_assets: list[dict[str, Any]] = []
    if (
        app_download_decision is not None
        and getattr(app_download_decision, "intent", None) == "asset_keyword_request"
    ):
        asset_keyword_assets = list(getattr(app_download_decision, "assets", []) or [])

    async with AsyncSessionLocal() as db:
        if asset_keyword_assets:
            # Explicit photo/video keyword requests should still deliver media even if
            # the acknowledgement text was sent recently.
            pass
        elif await should_skip_duplicate_outbound(
            db,
            user_id=user_id,
            content=reply_text,
            trace_id=trace_id,
            source="mtproto_auto_reply",
            redis=redis,
        ):
            return
        if await inbound_reply_turn_stale(
            db,
            conversation_id=conv_id,
            trigger_message_id=reply_trigger_message_id,
            claimed_message_ids=claimed_message_ids,
        ):
            log.bind(
                coalesced_trigger_message_id=reply_trigger_message_id,
                coalesced_message_count=len(claimed_message_ids),
            ).info("mtproto.inbound.coalesced_stale_skip_send")
            return

    peer = getattr(event, "chat_id", None) or sender_id

    sent = None
    sent_id = ""
    assistant_msg_id = str(uuid.uuid4())
    if asset_keyword_assets:
        first_persist = True
        for asset in asset_keyword_assets:
            asset_payload = dict(asset)
            if first_persist and reply_text.strip():
                asset_payload["caption"] = reply_text.strip()
            asset_content = str(asset_payload.get("asset_url") or "")
            async with AsyncSessionLocal() as db:
                if await should_skip_duplicate_outbound(
                    db,
                    user_id=user_id,
                    content=asset_content,
                    trace_id=trace_id,
                    source="mtproto_auto_reply_asset",
                    redis=redis,
                ):
                    continue
            sent = await send_mtproto_asset(
                client,
                peer,
                asset_payload,
                trace_id=trace_id,
            )
            if sent is None:
                continue
            persist_content = asset_content
            if asset_payload.get("caption"):
                persist_content = f"{asset_payload['caption']}\n{asset_content}"
            persisted_id = await _persist_message(
                conv_id=conv_id,
                sender_type="assistant",
                sender_id=str(account_id),
                content=persist_content,
                model_name=(
                    "profile_intake"
                    if profile_intake_only
                    else (
                        "system_auto_reply"
                        if outbound_only_reply
                        else ("realtime_ai" if first_persist else "script_asset")
                    )
                ),
                message_id=assistant_msg_id if first_persist else None,
            )
            if first_persist:
                assistant_msg_id = persisted_id
                first_persist = False
    else:
        telegram_reply_text = render_tracking_links_as_html_cta(
            reply_text,
            user_text=reply_user_text,
        )
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
            model_name=(
                "profile_intake"
                if profile_intake_only
                else ("system_auto_reply" if outbound_only_reply else "realtime_ai")
            ),
            message_id=assistant_msg_id,
        )
    if sent is None and not asset_keyword_assets:
        return
    if asset_keyword_assets and sent is None:
        return
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
    if (
        app_download_decision is not None
        and not asset_keyword_assets
        and not is_t1_sixth_message_decision(app_download_decision)
    ):
        for asset in app_download_decision.assets:
            asset_content = str(asset.get("asset_url") or "")
            async with AsyncSessionLocal() as db:
                if await should_skip_duplicate_outbound(
                    db,
                    user_id=user_id,
                    content=asset_content,
                    trace_id=trace_id,
                    source="mtproto_auto_reply_asset",
                    redis=redis,
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
                    model_name="script_asset",
                )
    try:
        await _push_context(redis, conv_id, "assistant", reply_text, assistant_msg_id)
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("mtproto.reply.ctx_push_failed")
    async with AsyncSessionLocal() as db:
        try:
            handed = await maybe_handoff_t1_after_ai_cap(
                db,
                user_id=user_id,
                conversation_id=conv_id,
                trace_id=trace_id,
            )
            if handed:
                await db.commit()
                log.info("mtproto.t1_ai_cap.handoff")
        except Exception as exc:
            await db.rollback()
            log.bind(error_type=type(exc).__name__).warning("mtproto.t1_ai_cap.handoff_failed")
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
                        "mtproto.video_request_handoff.keyword_guided_inbound"
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
