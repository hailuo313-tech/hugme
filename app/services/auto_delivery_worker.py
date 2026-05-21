"""B/C/D auto-delivery worker for P3-15: AccountPool outbound with countdown."""

import asyncio
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
from services.mtproto.account_routing import route_redis_key
from services.telegram_account_manager import telegram_account_manager

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger
except ModuleNotFoundError:
    AsyncIOScheduler = None  # type: ignore[assignment]
    IntervalTrigger = None  # type: ignore[assignment]

_ADVISORY_LOCK_KEY = 6_300_422
JOB_ID = "auto_delivery_worker_tick"

_scheduler: Optional[AsyncIOScheduler] = None
_account_pool: Optional[AccountPool] = None


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


async def _claim_bcd_message(session: AsyncSession) -> dict[str, Any] | None:
    """Claim one pending B/C/D level message that should be sent now."""
    row = (
        await session.execute(
            text(
                """
                WITH c AS (
                    SELECT ms.id
                    FROM message_schedules ms
                    JOIN users u ON ms.user_id = u.id::text
                    WHERE ms.status = 'pending'
                      AND (ms.send_at IS NULL OR ms.send_at <= NOW())
                      AND ms.retry_count < ms.max_retries
                      AND u.level IN ('B', 'C', 'D')
                    ORDER BY ms.priority DESC, ms.send_at ASC NULLS LAST, ms.created_at ASC
                    FOR UPDATE SKIP LOCKED
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
            )
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


async def _send_via_account_pool(
    user_id: str,
    chat_id: int,
    content: str,
    trace_id: Optional[str] = None,
) -> bool:
    """Send message via AccountPool with human-like delay."""
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
        "claimed": 0,
        "sent": 0,
        "failed": 0,
        "skipped_no_lock": 0,
        "skipped_no_pool": 0,
        "error": None,
    }

    message_id: str | None = None

    try:
        async with AsyncSessionLocal() as session:
            # Get advisory lock
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

            try:
                # Check AccountPool
                if _account_pool is None:
                    stats["skipped_no_pool"] = 1
                    log.warning("auto_delivery_worker.tick.skip_no_pool")
                    return stats

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

                log.bind(
                    message_id=message_id,
                    user_id=user_id,
                    message_type=message["message_type"],
                ).info("auto_delivery_worker.tick.claimed")

                # Send via AccountPool
                if chat_id:
                    success = await _send_via_account_pool(
                        user_id=user_id,
                        chat_id=chat_id,
                        content=content,
                        trace_id=trace_id,
                    )

                    if success:
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

    except Exception as e:
        log.error(f"auto_delivery_worker.tick.outer_error: {e}")
        stats["error"] = str(e)

    return stats


def start_scheduler() -> None:
    """Start the auto-delivery worker scheduler."""
    global _scheduler
    if _scheduler is None:
        logger.warning("APScheduler not available, auto-delivery worker scheduler not started")
        return

    if _scheduler.running:
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
    return {
        "running": _scheduler is not None and _scheduler.running,
        "job_id": JOB_ID if _scheduler else None,
        "job_exists": _scheduler is not None and JOB_ID in _scheduler
        if _scheduler else False,
        "account_pool_initialized": _account_pool is not None,
    }