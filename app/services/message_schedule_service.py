"""Message schedule service for P3-13: Redis pending queue + send_at."""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import AsyncSessionLocal
from models.message_schedule import MessageSchedule

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger
except ModuleNotFoundError:
    AsyncIOScheduler = None  # type: ignore[assignment]
    IntervalTrigger = None  # type: ignore[assignment]

_ADVISORY_LOCK_KEY = 6_300_421
JOB_ID = "message_schedule_tick"

_scheduler: Optional[AsyncIOScheduler] = None


async def _claim_one_message(session: AsyncSession) -> dict[str, Any] | None:
    """Claim one pending message that should be sent now."""
    row = (
        await session.execute(
            text(
                """
                WITH c AS (
                    SELECT id
                    FROM message_schedules
                    WHERE status = 'pending'
                      AND (send_at IS NULL OR send_at <= NOW())
                      AND retry_count < max_retries
                    ORDER BY priority DESC, send_at ASC NULLS LAST, created_at ASC
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


async def _send_message_via_telegram(
    account_id: str,
    chat_id: int,
    content: str,
    trace_id: Optional[str] = None,
) -> bool:
    """Send message via Telegram using MTProto account."""
    try:
        from services.telegram_account_manager import telegram_account_manager
        from services.telegram_send import send_telegram_text

        # Get Telegram client
        from uuid import UUID
        client = await telegram_account_manager.get_client(UUID(account_id))
        if not client:
            logger.error(f"Telegram account {account_id} not connected")
            return False

        # Send message
        message_id = await send_telegram_text(
            chat_id=chat_id,
            text_content=content,
            trace_id=trace_id,
        )

        return message_id is not None

    except Exception as e:
        logger.error(f"Error sending message via Telegram: {e}")
        return False


async def add_scheduled_message(
    user_id: str,
    external_user_id: str,
    message_type: str,
    content: str,
    platform: str = "telegram_real_user",
    account_id: Optional[str] = None,
    chat_id: Optional[int] = None,
    send_at: Optional[datetime] = None,
    priority: int = 0,
    metadata: Optional[dict] = None,
    trace_id: Optional[str] = None,
) -> str:
    """Add a message to the pending queue with optional send_at time."""
    async with AsyncSessionLocal() as session:
        schedule = MessageSchedule(
            user_id=user_id,
            external_user_id=external_user_id,
            message_type=message_type,
            content=content,
            platform=platform,
            account_id=account_id,
            chat_id=chat_id,
            status="pending",
            send_at=send_at,
            priority=priority,
            metadata_json=metadata or {},
            trace_id=trace_id,
        )
        session.add(schedule)
        await session.commit()
        await session.refresh(schedule)

        logger.info(
            f"Added scheduled message {schedule.id} for user {user_id}, "
            f"send_at={send_at}, priority={priority}"
        )

        return str(schedule.id)


async def run_one_tick(trace_id: Optional[str] = None) -> dict[str, Any]:
    """Process one pending message that should be sent now."""
    trace_id = trace_id or f"msg-{int(datetime.utcnow().timestamp())}"
    log = logger.bind(component="message_schedule_service", trace_id=trace_id)
    stats: dict[str, Any] = {
        "claimed": 0,
        "sent": 0,
        "failed": 0,
        "skipped_no_lock": 0,
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
                log.info("message_schedule_service.tick.skip_no_lock")
                return stats

            try:
                # Claim one message to send
                message = await _claim_one_message(session)
                if not message:
                    log.info("message_schedule_service.tick.empty")
                    return stats

                stats["claimed"] = 1
                message_id = str(message["id"])
                content = message["content"]
                account_id = message.get("account_id")
                chat_id = message.get("chat_id")

                log.bind(
                    message_id=message_id,
                    user_id=message["user_id"],
                    message_type=message["message_type"],
                ).info("message_schedule_service.tick.claimed")

                # Send message via Telegram
                if account_id and chat_id:
                    success = await _send_message_via_telegram(
                        account_id=account_id,
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
                        log.bind(message_id=message_id).info("message_schedule_service.tick.sent")
                    else:
                        await _finalize_message(
                            session,
                            message_id=message_id,
                            status="failed",
                            failure_reason="telegram_send_failed",
                        )
                        stats["failed"] = 1
                        log.bind(message_id=message_id).warning("message_schedule_service.tick.failed")
                else:
                    # No account_id or chat_id, mark as failed
                    await _finalize_message(
                        session,
                        message_id=message_id,
                        status="failed",
                        failure_reason="missing_account_or_chat_id",
                    )
                    stats["failed"] = 1
                    log.bind(message_id=message_id).warning("message_schedule_service.tick.no_account")

            except Exception as e:
                log.error(f"message_schedule_service.tick.error: {e}")
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
        log.error(f"message_schedule_service.tick.outer_error: {e}")
        stats["error"] = str(e)

    return stats


def start_scheduler() -> None:
    """Start the message schedule scheduler."""
    global _scheduler
    if AsyncIOScheduler is None or IntervalTrigger is None:
        logger.warning("APScheduler not available, message schedule scheduler not started")
        return
    if not getattr(settings, "MESSAGE_SCHEDULE_ENABLED", False):
        logger.info("Message schedule scheduler disabled")
        return

    if _scheduler is not None and _scheduler.running:
        logger.warning("Message schedule scheduler already running")
        return

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_one_tick,
        trigger=IntervalTrigger(
            seconds=getattr(settings, "MESSAGE_SCHEDULE_POLL_SECONDS", 20)
        ),
        id=JOB_ID,
        max_instances=getattr(settings, "MESSAGE_SCHEDULE_SCHEDULER_MAX_INSTANCES", 1),
    )
    _scheduler.start()
    logger.info("Message schedule scheduler started")


def shutdown_scheduler() -> None:
    """Shutdown the message schedule scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
        logger.info("Message schedule scheduler shutdown")


def get_scheduler_status() -> dict:
    """Get scheduler status."""
    return {
        "running": _scheduler is not None and _scheduler.running,
        "job_id": JOB_ID if _scheduler else None,
        "job_exists": _scheduler is not None and JOB_ID in _scheduler
        if _scheduler else False,
    }
