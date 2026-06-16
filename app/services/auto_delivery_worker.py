"""B/C/D auto-delivery worker plus P3-17 timeout fallback delivery."""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import AsyncSessionLocal
from services.human_delay_calculator import calculate_human_delay
from services.mtproto.account_pool import AccountPool
from services.mtproto.account_routing import pin_mtproto_account_route
from services.telegram_account_manager import telegram_account_manager
from services.telegram_send import telegram_chat_id_from_external
from services.app_download_nurture import (
    APP_DOWNLOAD_MESSAGE_TYPE,
    APP_DOWNLOAD_NURTURE_DELIVERY_MODE,
    persist_auto_delivery_message,
    prepare_nurture_message_for_send,
    resolve_nurture_sender_account_id,
    should_skip_stale_nurture_message,
)
from services.link_cooldown import is_conversation_link_cooldown_active
from services.message_repeat_guard import should_skip_duplicate_outbound

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger
except ModuleNotFoundError:
    AsyncIOScheduler = None  # type: ignore[assignment]
    IntervalTrigger = None  # type: ignore[assignment]

_ADVISORY_LOCK_KEY = 6_300_422
JOB_ID = "auto_delivery_worker_tick"
TIMEOUT_FALLBACK_MESSAGE_TYPE = "timeout_fallback"
TIMEOUT_FALLBACK_DELIVERY_MODE = "timeout_fallback"
DEFAULT_TIMEOUT_FALLBACK_SCRIPT_HIT_ID = "default.timeout_fallback.safe_reply"
DEFAULT_TIMEOUT_FALLBACK_CONTENT = "我先接住你刚才这条消息。真人同事稍后继续跟进，我们也可以先把最重要的点说清楚。"
ASSISTANT_QUIET_COOLDOWN_SECONDS = 290
ASSISTANT_QUIET_COOLDOWN_REASON = "assistant_quiet_cooldown_290s"

_scheduler: Optional[AsyncIOScheduler] = None
_account_pool: Optional[AccountPool] = None


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    data = row._mapping if hasattr(row, "_mapping") else row
    if hasattr(data, "get"):
        return data.get(key, default)
    return getattr(data, key, default)


def _normalize_timeout_fallback_script(row: Any | None) -> dict[str, str]:
    """Return a user-facing default fallback script with a stable hit id."""
    if row is None:
        return {
            "script_hit_id": DEFAULT_TIMEOUT_FALLBACK_SCRIPT_HIT_ID,
            "content": DEFAULT_TIMEOUT_FALLBACK_CONTENT,
        }

    script_hit_id = str(_row_get(row, "id") or "").strip()
    content = str(_row_get(row, "content") or "").strip()
    return {
        "script_hit_id": script_hit_id or DEFAULT_TIMEOUT_FALLBACK_SCRIPT_HIT_ID,
        "content": content or DEFAULT_TIMEOUT_FALLBACK_CONTENT,
    }


def _build_timeout_fallback_metadata(
    *,
    handoff_task_id: str,
    conversation_id: str | None,
    user_level: str | None,
    script_hit_id: str,
    trace_id: str | None,
) -> dict[str, Any]:
    return {
        "delivery_mode": TIMEOUT_FALLBACK_DELIVERY_MODE,
        "fallback_reason": "handoff_draft_timeout_120s",
        "script_hit_id": script_hit_id,
        "script_match_stage": "timeout_fallback",
        "source_handoff_task_id": handoff_task_id,
        "conversation_id": conversation_id,
        "user_level": user_level,
        "trace_id": trace_id,
    }


def _is_timeout_fallback_message(message: dict[str, Any]) -> bool:
    metadata = message.get("metadata") or {}
    return (
        message.get("message_type") == TIMEOUT_FALLBACK_MESSAGE_TYPE
        or metadata.get("delivery_mode") == TIMEOUT_FALLBACK_DELIVERY_MODE
    )


def _is_app_download_nurture_message(message: dict[str, Any]) -> bool:
    metadata = message.get("metadata") or {}
    return (
        message.get("message_type") == APP_DOWNLOAD_MESSAGE_TYPE
        or metadata.get("delivery_mode") == APP_DOWNLOAD_NURTURE_DELIVERY_MODE
    )


async def _get_redis():
    """Get Redis client."""
    try:
        from core.redis import get_redis
        return await get_redis()
    except Exception as e:
        logger.warning(f"Failed to get Redis client: {e}")
        return None


async def _init_account_pool():
    """Initialize AccountPool with active Telegram accounts."""
    global _account_pool

    try:
        # Get active Telegram accounts
        accounts = await telegram_account_manager.get_active_accounts()
        if not accounts:
            logger.warning("No active Telegram accounts found for AccountPool")
            return False

        account_ids = [str(account.id) for account in accounts]
        logger.info(f"Initializing AccountPool with {len(account_ids)} accounts")

        # Create AccountPool
        redis = await _get_redis()

        async def client_resolver(account_id: str):
            """Resolve Telegram client by account ID."""
            return await telegram_account_manager.get_client(UUID(account_id))

        _account_pool = AccountPool(
            account_ids=account_ids,
            client_resolver=client_resolver,
            redis=redis,
            route_ttl_seconds=86400,  # 24 hours
        )

        logger.info("AccountPool initialized successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to initialize AccountPool: {e}")
        return False


async def _select_timeout_fallback_script(
    session: AsyncSession,
    *,
    platform: str,
    user_level: str,
) -> dict[str, str]:
    """Choose the approved default fallback script for timeout delivery."""
    row = (
        await session.execute(
            text(
                """
                SELECT id, content
                FROM script_templates
                WHERE status = 'approved'
                  AND category_key = 'fallback'
                  AND (platform = :platform OR channel = :platform OR platform IS NULL)
                  AND (hook IN ('reply', 'outbound') OR hook IS NULL)
                ORDER BY
                  CASE
                    WHEN user_level = :user_level THEN 0
                    WHEN user_level IS NULL THEN 1
                    WHEN user_level IN ('B', 'C', 'D') THEN 2
                    ELSE 3
                  END,
                  CASE WHEN hook = 'reply' THEN 0 WHEN hook = 'outbound' THEN 1 ELSE 2 END,
                  updated_at DESC,
                  created_at DESC
                LIMIT 1
                """
            ),
            {"platform": platform, "user_level": user_level},
        )
    ).mappings().first()
    return _normalize_timeout_fallback_script(row)


async def schedule_expired_timeout_fallbacks(
    session: AsyncSession,
    *,
    trace_id: str | None = None,
    batch_size: int = 10,
) -> int:
    """Queue S/A draft timeout fallback messages with script_hit_id metadata."""
    rows = (
        await session.execute(
            text(
                """
                SELECT
                    ht.id AS handoff_task_id,
                    ht.user_id::text AS user_id,
                    ht.conversation_id::text AS conversation_id,
                    u.external_id AS external_user_id,
                    COALESCE(p.user_level, 'C') AS user_level,
                    COALESCE(NULLIF(u.channel, ''), 'telegram_real_user') AS platform,
                    ht.draft_expires_at
                FROM handoff_tasks ht
                JOIN users u ON ht.user_id = u.id
                LEFT JOIN user_profiles p ON p.user_id = u.id
                WHERE ht.status IN ('pending', 'HUMAN_LOCKED')
                  AND COALESCE(p.user_level, 'C') IN ('S', 'A')
                  AND ht.draft_expires_at IS NOT NULL
                  AND ht.draft_expires_at <= NOW()
                  AND NOT EXISTS (
                      SELECT 1
                      FROM message_schedules ms
                      WHERE ms.metadata->>'delivery_mode' = :delivery_mode
                        AND ms.metadata->>'source_handoff_task_id' = ht.id::text
                  )
                ORDER BY ht.draft_expires_at ASC
                FOR UPDATE OF ht SKIP LOCKED
                LIMIT :batch_size
                """
            ),
            {
                "delivery_mode": TIMEOUT_FALLBACK_DELIVERY_MODE,
                "batch_size": max(1, batch_size),
            },
        )
    ).mappings().all()

    queued = 0
    for row in rows:
        platform = str(_row_get(row, "platform") or "telegram_real_user")
        if platform == "telegram":
            platform = "telegram_real_user"
        user_level = str(_row_get(row, "user_level") or "")
        external_user_id = str(_row_get(row, "external_user_id") or "")
        chat_id = telegram_chat_id_from_external(external_user_id)
        script = await _select_timeout_fallback_script(
            session,
            platform=platform,
            user_level=user_level,
        )
        handoff_task_id = str(_row_get(row, "handoff_task_id"))
        conversation_id = _row_get(row, "conversation_id")
        metadata = _build_timeout_fallback_metadata(
            handoff_task_id=handoff_task_id,
            conversation_id=str(conversation_id) if conversation_id else None,
            user_level=user_level,
            script_hit_id=script["script_hit_id"],
            trace_id=trace_id,
        )

        await session.execute(
            text(
                """
                INSERT INTO message_schedules (
                    user_id,
                    external_user_id,
                    message_type,
                    content,
                    platform,
                    chat_id,
                    status,
                    send_at,
                    priority,
                    metadata,
                    trace_id
                ) VALUES (
                    :user_id,
                    :external_user_id,
                    :message_type,
                    :content,
                    :platform,
                    :chat_id,
                    'pending',
                    NOW(),
                    :priority,
                    CAST(:metadata AS jsonb),
                    :trace_id
                )
                """
            ),
            {
                "user_id": str(_row_get(row, "user_id")),
                "external_user_id": external_user_id,
                "message_type": TIMEOUT_FALLBACK_MESSAGE_TYPE,
                "content": script["content"],
                "platform": platform,
                "chat_id": chat_id,
                "priority": 100,
                "metadata": json.dumps(metadata, ensure_ascii=False),
                "trace_id": trace_id,
            },
        )
        queued += 1

        logger.bind(
            trace_id=trace_id,
            handoff_task_id=handoff_task_id,
            user_level=user_level,
            script_hit_id=script["script_hit_id"],
        ).info("auto_delivery_worker.timeout_fallback.queued")

    if queued:
        await session.commit()
    return queued


async def _claim_bcd_message(session: AsyncSession) -> dict[str, Any] | None:
    """Claim one pending B/C/D message or P3-17 timeout fallback."""
    row = (
        await session.execute(
            text(
                """
                WITH c AS (
                    SELECT ms.id
                    FROM message_schedules ms
                    JOIN users u ON ms.user_id = u.id::text
                    LEFT JOIN user_profiles p ON p.user_id = u.id
                    WHERE ms.status = 'pending'
                      AND (ms.send_at IS NULL OR ms.send_at <= NOW())
                      AND ms.retry_count < ms.max_retries
                      AND (
                          COALESCE(p.user_level, 'C') IN ('B', 'C', 'D')
                          OR ms.metadata->>'delivery_mode' = :delivery_mode
                          OR ms.metadata->>'delivery_mode' = :app_download_delivery_mode
                          OR ms.message_type = :timeout_message_type
                          OR ms.message_type = :app_download_message_type
                      )
                    ORDER BY ms.priority DESC, ms.send_at ASC NULLS LAST, ms.created_at ASC
                    FOR UPDATE OF ms SKIP LOCKED
                    LIMIT 1
                )
                UPDATE message_schedules ms
                SET status = 'sending',
                    updated_at = NOW()
                FROM c
                WHERE ms.id = c.id
                RETURNING ms.id, ms.user_id, ms.external_user_id, ms.message_type,
                       ms.content, ms.platform, ms.account_id, ms.chat_id,
                       ms.metadata, ms.trace_id, ms.retry_count
                """
            ),
            {
                "delivery_mode": TIMEOUT_FALLBACK_DELIVERY_MODE,
                "timeout_message_type": TIMEOUT_FALLBACK_MESSAGE_TYPE,
                "app_download_delivery_mode": APP_DOWNLOAD_NURTURE_DELIVERY_MODE,
                "app_download_message_type": APP_DOWNLOAD_MESSAGE_TYPE,
            },
        )
    ).mappings().first()
    if not row:
        return None
    await session.commit()
    return dict(row)


async def _finalize_message(
    session: AsyncSession,
    *,
    message_id: str,
    status: str,
    failure_reason: str | None = None,
) -> None:
    """Finalize message status after send attempt."""
    if status == "sent":
        await session.execute(
            text(
                """
                UPDATE message_schedules
                SET status = 'sent',
                    sent_at = NOW(),
                    failure_reason = NULL,
                    updated_at = NOW()
                WHERE id = :id AND status = 'sending'
                """
            ),
            {"id": message_id},
        )
    else:
        await session.execute(
            text(
                """
                UPDATE message_schedules
                SET status = 'failed',
                    failure_reason = :reason,
                    retry_count = retry_count + 1,
                    updated_at = NOW()
                WHERE id = :id AND status = 'sending'
                """
            ),
            {"id": message_id, "reason": failure_reason or "send_failed"},
        )
    await session.commit()


async def _get_assistant_quiet_cooldown_until(
    session: AsyncSession,
    *,
    conversation_id: str | None,
) -> datetime | None:
    """Return the earliest send time if the last message is a recent system reply."""
    if not conversation_id:
        return None

    row = (
        await session.execute(
            text(
                """
                SELECT
                    sender_type,
                    created_at + (:cooldown_seconds * interval '1 second') AS allow_after,
                    EXTRACT(
                        EPOCH FROM (
                            created_at + (:cooldown_seconds * interval '1 second') - NOW()
                        )
                    ) AS remaining_seconds
                FROM messages
                WHERE conversation_id = CAST(:conversation_id AS uuid)
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {
                "conversation_id": conversation_id,
                "cooldown_seconds": ASSISTANT_QUIET_COOLDOWN_SECONDS,
            },
        )
    ).mappings().first()
    if not row:
        return None

    sender_type = str(row.get("sender_type") or "").lower()
    remaining_seconds = float(row.get("remaining_seconds") or 0)
    if sender_type in {"assistant", "operator", "system"} and remaining_seconds > 0:
        return row.get("allow_after")
    return None


async def _defer_message_until(
    session: AsyncSession,
    *,
    message_id: str,
    send_at: datetime,
    reason: str,
) -> None:
    """Put a claimed message back to pending without consuming retry budget."""
    await session.execute(
        text(
            """
            UPDATE message_schedules
            SET status = 'pending',
                send_at = :send_at,
                failure_reason = :reason,
                updated_at = NOW()
            WHERE id = :id AND status = 'sending'
            """
        ),
        {"id": message_id, "send_at": send_at, "reason": reason},
    )
    await session.commit()


async def _resolve_delivery_account_id(
    session: AsyncSession,
    *,
    message: dict[str, Any],
) -> str | None:
    """Prefer the MTProto account that owns the live dialog for this follow-up."""
    direct = message.get("account_id")
    if direct:
        return str(direct)

    metadata = message.get("metadata") or {}
    sender_account_id = metadata.get("sender_account_id")
    if sender_account_id:
        return str(sender_account_id)

    return await resolve_nurture_sender_account_id(
        session,
        conversation_id=str(metadata.get("conversation_id") or ""),
    )


async def _send_via_mtproto_account(
    *,
    account_id: str,
    chat_id: int,
    content: str,
    trace_id: Optional[str] = None,
    telegram_access_hash: int | None = None,
) -> bool:
    """Send using a specific MTProto account instead of hash routing."""
    try:
        from services.mtproto.peer_resolve import resolve_telethon_peer

        client = await telegram_account_manager.get_client(UUID(account_id))
        if client is None:
            logger.bind(account_id=account_id, trace_id=trace_id).warning(
                "auto_delivery_worker.account_client_missing"
            )
            return False

        delay_result = calculate_human_delay(content)
        await asyncio.sleep(delay_result.delay_seconds)

        peer = await resolve_telethon_peer(
            client,
            chat_id,
            access_hash=telegram_access_hash,
        )

        from services.mtproto.human_like_send import send_human_like_message

        await send_human_like_message(client, peer, content)
        logger.bind(
            trace_id=trace_id,
            account_id=account_id,
            chat_id=chat_id,
        ).info("auto_delivery_worker.sent_via_account")
        return True
    except Exception as exc:
        logger.bind(
            trace_id=trace_id,
            account_id=account_id,
            chat_id=chat_id,
            error_type=type(exc).__name__,
        ).error(f"auto_delivery_worker.account_send_error: {exc}")
        return False


async def _send_via_account_pool(
    user_id: str,
    chat_id: int,
    content: str,
    trace_id: Optional[str] = None,
    preferred_account_id: str | None = None,
    telegram_access_hash: int | None = None,
) -> bool:
    """Send message via AccountPool with human-like delay."""
    if preferred_account_id:
        redis = await _get_redis()
        await pin_mtproto_account_route(
            redis,
            user_id=user_id,
            account_id=preferred_account_id,
        )
        if await _send_via_mtproto_account(
            account_id=preferred_account_id,
            chat_id=chat_id,
            content=content,
            trace_id=trace_id,
            telegram_access_hash=telegram_access_hash,
        ):
            return True

        from services.call_broadcast.peers import resolve_account_and_access_hash

        fallback_account_id, fallback_hash = await resolve_account_and_access_hash(
            chat_id=chat_id,
            preferred_account_id=preferred_account_id,
        )
        if fallback_account_id and fallback_account_id != preferred_account_id:
            await pin_mtproto_account_route(
                redis,
                user_id=user_id,
                account_id=fallback_account_id,
            )
            fallback_access_hash = (
                int(fallback_hash) if fallback_hash is not None else telegram_access_hash
            )
            return await _send_via_mtproto_account(
                account_id=fallback_account_id,
                chat_id=chat_id,
                content=content,
                trace_id=trace_id,
                telegram_access_hash=fallback_access_hash,
            )
        return False

    if _account_pool is None:
        logger.error("AccountPool not initialized")
        return False

    try:
        from telethon.tl.types import PeerUser

        # Create peer for the user
        peer = PeerUser(user_id=chat_id)

        # Calculate human-like delay
        delay_result = calculate_human_delay(content)
        delay_seconds = delay_result.delay_seconds

        logger.bind(
            trace_id=trace_id,
            user_id=user_id,
            chat_id=chat_id,
            delay_seconds=delay_seconds,
        ).info("auto_delivery_worker.sending_with_delay")

        # Wait for calculated delay
        await asyncio.sleep(delay_seconds)

        # Send via AccountPool
        result = await _account_pool.send_message(
            user_id=user_id,
            peer=peer,
            text=content,
            sleep=asyncio.sleep,
        )

        logger.bind(
            trace_id=trace_id,
            user_id=user_id,
            account_id=result.account_id,
        ).info("auto_delivery_worker.sent_via_account_pool")

        return True

    except Exception as e:
        logger.bind(trace_id=trace_id, user_id=user_id).error(f"auto_delivery_worker.send_error: {e}")
        return False


async def run_one_tick(trace_id: Optional[str] = None) -> dict[str, Any]:
    """Process one B/C/D level pending message."""
    trace_id = trace_id or f"auto-{int(datetime.utcnow().timestamp())}"
    log = logger.bind(component="auto_delivery_worker", trace_id=trace_id)
    stats: dict[str, Any] = {
        "timeout_fallback_queued": 0,
        "app_download_followup_queued": 0,
        "claimed": 0,
        "sent": 0,
        "failed": 0,
        "skipped_stale": 0,
        "deferred_quiet_cooldown": 0,
        "skipped_no_lock": 0,
        "skipped_no_pool": 0,
        "error": None,
    }

    message_id: str | None = None

    try:
        async with AsyncSessionLocal() as session:
            got_lock = False
            got = (
                await session.execute(
                    text("SELECT pg_try_advisory_lock(:k)"),
                    {"k": _ADVISORY_LOCK_KEY},
                )
            ).scalar()
            if not got:
                stats["skipped_no_lock"] = 1
                log.info("auto_delivery_worker.tick.skip_no_lock")
                return stats
            got_lock = True

            try:
                # Check AccountPool
                if _account_pool is None:
                    stats["skipped_no_pool"] = 1
                    log.warning("auto_delivery_worker.tick.skip_no_pool")
                    return stats

                # P3-17: turn expired S/A handoff drafts into deliverable fallback rows.
                stats["timeout_fallback_queued"] = await schedule_expired_timeout_fallbacks(
                    session,
                    trace_id=trace_id,
                )
                stats["app_download_followup_queued"] = 0

                # Claim one B/C/D message to send
                message = await _claim_bcd_message(session)
                if not message:
                    log.info("auto_delivery_worker.tick.empty")
                    return stats

                stats["claimed"] = 1
                message_id = str(message["id"])
                user_id = message["user_id"]
                content = message["content"]
                chat_id = message.get("chat_id")
                metadata = message.get("metadata") or {}
                conversation_id = metadata.get("conversation_id")

                cooldown_until = await _get_assistant_quiet_cooldown_until(
                    session,
                    conversation_id=str(conversation_id) if conversation_id else None,
                )
                if cooldown_until:
                    await _defer_message_until(
                        session,
                        message_id=message_id,
                        send_at=cooldown_until,
                        reason=ASSISTANT_QUIET_COOLDOWN_REASON,
                    )
                    stats["deferred_quiet_cooldown"] = 1
                    log.bind(
                        message_id=message_id,
                        conversation_id=conversation_id,
                        cooldown_until=cooldown_until.isoformat()
                        if hasattr(cooldown_until, "isoformat")
                        else str(cooldown_until),
                    ).info("auto_delivery_worker.tick.quiet_cooldown_defer")
                    return stats

                stale_reason = await should_skip_stale_nurture_message(
                    session,
                    message=message,
                )
                if stale_reason:
                    await _finalize_message(
                        session,
                        message_id=message_id,
                        status="failed",
                        failure_reason=f"stale:{stale_reason}",
                    )
                    stats["skipped_stale"] = 1
                    log.bind(message_id=message_id, stale_reason=stale_reason).info(
                        "auto_delivery_worker.tick.stale_skip"
                    )
                    return stats

                if (
                    _is_app_download_nurture_message(message)
                    and conversation_id
                    and (message.get("metadata") or {}).get("nurture_kind") != "video_chat"
                    and await is_conversation_link_cooldown_active(
                        session,
                        conversation_id=str(conversation_id),
                    )
                ):
                    await _finalize_message(
                        session,
                        message_id=message_id,
                        status="failed",
                        failure_reason="stale:link_cooldown",
                    )
                    stats["skipped_stale"] = 1
                    log.bind(message_id=message_id, stale_reason="link_cooldown").info(
                        "auto_delivery_worker.tick.link_cooldown_skip"
                    )
                    return stats

                content = await prepare_nurture_message_for_send(
                    session,
                    message=message,
                    trace_id=trace_id,
                )
                if await should_skip_duplicate_outbound(
                    session,
                    user_id=str(user_id),
                    content=content,
                    trace_id=trace_id,
                    source="auto_delivery_worker",
                ):
                    await _finalize_message(
                        session,
                        message_id=message_id,
                        status="failed",
                        failure_reason="duplicate:repeat_cooldown",
                    )
                    stats["skipped_stale"] = 1
                    log.bind(message_id=message_id).info(
                        "auto_delivery_worker.tick.duplicate_content_skip"
                    )
                    return stats
                preferred_account_id = await _resolve_delivery_account_id(
                    session,
                    message=message,
                )
                raw_access_hash = (message.get("metadata") or {}).get("telegram_access_hash")
                telegram_access_hash = (
                    int(str(raw_access_hash)) if raw_access_hash is not None else None
                )
                await session.commit()

                log.bind(
                    message_id=message_id,
                    user_id=user_id,
                    message_type=message["message_type"],
                    script_hit_id=(message.get("metadata") or {}).get("script_hit_id"),
                    timeout_fallback=_is_timeout_fallback_message(message),
                    app_download_nurture=_is_app_download_nurture_message(message),
                ).info("auto_delivery_worker.tick.claimed")

                # Send via AccountPool
                if chat_id:
                    success = await _send_via_account_pool(
                        user_id=user_id,
                        chat_id=chat_id,
                        content=content,
                        trace_id=trace_id,
                        preferred_account_id=preferred_account_id,
                        telegram_access_hash=telegram_access_hash,
                    )

                    if success:
                        sender_id = "auto_delivery_worker"
                        if _is_app_download_nurture_message(message):
                            try:
                                await persist_auto_delivery_message(
                                    session,
                                    message=message,
                                    content=content,
                                    sender_id=sender_id,
                                )
                            except Exception as persist_error:
                                log.bind(
                                    message_id=message_id,
                                    error_type=type(persist_error).__name__,
                                ).warning("auto_delivery_worker.persist_sent_message_failed")
                        await _finalize_message(
                            session,
                            message_id=message_id,
                            status="sent",
                        )
                        stats["sent"] = 1
                        log.bind(message_id=message_id).info("auto_delivery_worker.tick.sent")
                    else:
                        await _finalize_message(
                            session,
                            message_id=message_id,
                            status="failed",
                            failure_reason="account_pool_send_failed",
                        )
                        stats["failed"] = 1
                        log.bind(message_id=message_id).warning("auto_delivery_worker.tick.failed")
                else:
                    # No chat_id, mark as failed
                    await _finalize_message(
                        session,
                        message_id=message_id,
                        status="failed",
                        failure_reason="missing_chat_id",
                    )
                    stats["failed"] = 1
                    log.bind(message_id=message_id).warning("auto_delivery_worker.tick.no_chat_id")

            except Exception as e:
                log.error(f"auto_delivery_worker.tick.error: {e}")
                stats["error"] = str(e)
                if message_id:
                    try:
                        await _finalize_message(
                            session,
                            message_id=message_id,
                            status="failed",
                            failure_reason=f"exception:{type(e).__name__}",
                        )
                    except Exception as finalize_error:
                        log.error(f"Error finalizing message: {finalize_error}")
            finally:
                if got_lock:
                    try:
                        await session.execute(
                            text("SELECT pg_advisory_unlock(:k)"),
                            {"k": _ADVISORY_LOCK_KEY},
                        )
                        await session.commit()
                    except Exception as unlock_error:
                        log.bind(error_type=type(unlock_error).__name__).warning(
                            "auto_delivery_worker.tick.unlock_failed"
                        )

    except Exception as e:
        log.error(f"auto_delivery_worker.tick.outer_error: {e}")
        stats["error"] = str(e)

    return stats


def start_scheduler() -> None:
    """Start the auto-delivery worker scheduler."""
    global _scheduler
    if AsyncIOScheduler is None or IntervalTrigger is None:
        logger.warning("APScheduler not available, auto-delivery worker scheduler not started")
        return
    if not getattr(settings, "AUTO_DELIVERY_ENABLED", False):
        logger.info("Auto-delivery worker scheduler disabled")
        return

    if _scheduler is not None and _scheduler.running:
        logger.warning("Auto-delivery worker scheduler already running")
        return

    # Initialize AccountPool on startup
    asyncio.create_task(_init_account_pool())

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_one_tick,
        trigger=IntervalTrigger(
            seconds=getattr(settings, "AUTO_DELIVERY_POLL_SECONDS", 20)
        ),
        id=JOB_ID,
        max_instances=getattr(settings, "AUTO_DELIVERY_SCHEDULER_MAX_INSTANCES", 1),
    )
    _scheduler.start()
    logger.info("Auto-delivery worker scheduler started")


def shutdown_scheduler() -> None:
    """Shutdown the auto-delivery worker scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
        logger.info("Auto-delivery worker scheduler shutdown")


async def reinit_account_pool() -> bool:
    """Reinitialize AccountPool (for config reload or account changes)."""
    return await _init_account_pool()


def get_scheduler_status() -> dict:
    """Get scheduler status."""
    job_exists = False
    if _scheduler is not None:
        get_job = getattr(_scheduler, "get_job", None)
        if callable(get_job):
            job_exists = get_job(JOB_ID) is not None
        else:
            jobs = getattr(_scheduler, "jobs", None)
            if isinstance(jobs, list):
                job_exists = any(
                    getattr(job, "id", None) == JOB_ID
                    or (isinstance(job, tuple) and len(job) > 1 and job[1].get("id") == JOB_ID)
                    for job in jobs
                )
    return {
        "running": _scheduler is not None and _scheduler.running,
        "job_id": JOB_ID if _scheduler else None,
        "job_exists": job_exists,
        "account_pool_initialized": _account_pool is not None,
    }
