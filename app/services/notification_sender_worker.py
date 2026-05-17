"""D6-4 / V001-P0-4: 从 ``notification_tasks`` 拉取 pending 任务并真发 Telegram。

- 仅 ``channel = 'telegram'``；``scheduled_at <= NOW()``（或 NULL 视为可立即发送）。
- 抢单行：``FOR UPDATE SKIP LOCKED`` + ``UPDATE … SET status='sending'``，避免多 worker 重复发。
- 发送成功后 ``status='sent'``, ``sent_at=NOW()``；失败则 ``status='failed'`` + ``failure_reason``。
- ``NOTIFICATION_SENDER_ENABLED=False`` 时不注册 APScheduler（与 silent_reactivation / embedding 一致）。
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import AsyncSessionLocal
from services.minor_protection import should_block_push
from services.telegram_send import send_telegram_text, telegram_chat_id_from_external

_ADVISORY_LOCK_KEY = 6_300_420
JOB_ID = "notification_sender_tick"

_scheduler: Optional[AsyncIOScheduler] = None


def build_outbound_text(*, notification_type: str, payload: Any) -> str | None:
    """根据类型与 payload 生成出站文案；未知类型返回 None（由调用方记 failed）。"""
    p: dict[str, Any] = payload if isinstance(payload, dict) else {}
    n = (notification_type or "").strip().lower()

    if n == "silent_reactivation":
        tier = str(p.get("tier") or "D1").upper()
        lines = {
            "D1": (
                "Hi — we've been thinking of you. Whenever you're ready, "
                "we're here to chat. No rush."
            ),
            "D3": (
                "Hi — we'd love to pick up where you left off. "
                "If you feel like chatting, just send a message when it suits you."
            ),
            "D7": (
                "Hi — we'll step back for now. If you ever want to return, "
                "we're only a message away."
            ),
        }
        return lines.get(tier, lines["D1"])

    if n == "s5_care_checkin":
        return (
            "Hi — we're checking in. If things feel heavy, we're here to listen; "
            "message us whenever you feel able."
        )

    return None


async def _claim_one_task(session: AsyncSession) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                """
                WITH c AS (
                    SELECT id
                    FROM notification_tasks
                    WHERE status = 'pending'
                      AND channel = 'telegram'
                      AND (scheduled_at IS NULL OR scheduled_at <= NOW())
                    ORDER BY scheduled_at ASC NULLS LAST, created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE notification_tasks nt
                SET status = 'sending'
                FROM c
                WHERE nt.id = c.id
                RETURNING nt.id, nt.user_id, nt.channel, nt.notification_type, nt.payload
                """
            )
        )
    ).mappings().first()
    if not row:
        return None
    await session.commit()
    return dict(row)


async def _finalize_task(
    session: AsyncSession,
    *,
    task_id: str,
    status: str,
    failure_reason: str | None,
) -> None:
    if status == "sent":
        await session.execute(
            text(
                """
                UPDATE notification_tasks
                SET status = 'sent',
                    sent_at = NOW(),
                    failure_reason = NULL
                WHERE id = :id AND status = 'sending'
                """
            ),
            {"id": task_id},
        )
    else:
        await session.execute(
            text(
                """
                UPDATE notification_tasks
                SET status = 'failed',
                    failure_reason = :reason
                WHERE id = :id AND status = 'sending'
                """
            ),
            {"id": task_id, "reason": failure_reason or "send_failed"},
        )
    await session.commit()


def _normalize_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


async def run_one_tick(trace_id: Optional[str] = None) -> dict[str, Any]:
    """处理至多一条 pending 任务。返回统计 dict（便于测试 / 监控）。"""
    trace_id = trace_id or f"ntfy-{int(time.time())}"
    log = logger.bind(component="notification_sender_worker", trace_id=trace_id)
    stats: dict[str, Any] = {
        "claimed": 0,
        "sent": 0,
        "failed": 0,
        "skipped_no_lock": 0,
        "error": None,
    }

    if not settings.NOTIFICATION_SENDER_ENABLED:
        return stats

    task_id: str | None = None
    chat_id: int | None = None
    body: str | None = None

    try:
        async with AsyncSessionLocal() as session:
            got = (
                await session.execute(
                    text("SELECT pg_try_advisory_lock(:k)"),
                    {"k": _ADVISORY_LOCK_KEY},
                )
            ).scalar()
            if not got:
                stats["skipped_no_lock"] = 1
                log.info("notification_sender_worker.skip_no_lock")
                return stats

            try:
                task = await _claim_one_task(session)
                if not task:
                    log.info("notification_sender_worker.tick.empty")
                    return stats

                stats["claimed"] = 1
                task_id = str(task["id"])
                user_id = str(task["user_id"])
                ntype = str(task["notification_type"] or "")
                payload = _normalize_payload(task.get("payload"))

                body = build_outbound_text(notification_type=ntype, payload=payload)
                if body is None:
                    await _finalize_task(
                        session,
                        task_id=task_id,
                        status="failed",
                        failure_reason=f"unsupported_notification_type:{ntype}",
                    )
                    stats["failed"] = 1
                    log.bind(task_id=task_id, notification_type=ntype).warning(
                        "notification_sender_worker.unsupported_type"
                    )
                    task_id = None
                    return stats

                urow = (
                    await session.execute(
                        text(
                            """
                            SELECT channel, external_id, status, is_minor_suspected,
                                   notification_opt_in, opt_out_marketing
                            FROM users
                            WHERE id = :uid
                            """
                        ),
                        {"uid": user_id},
                    )
                ).mappings().first()

                if not urow or (urow.get("channel") or "").lower() != "telegram":
                    await _finalize_task(
                        session,
                        task_id=task_id,
                        status="failed",
                        failure_reason="user_not_telegram_channel",
                    )
                    stats["failed"] = 1
                    task_id = None
                    return stats

                if (
                    (urow.get("status") or "active") != "active"
                    or not bool(urow.get("notification_opt_in"))
                    or bool(urow.get("opt_out_marketing"))
                    or should_block_push(
                        is_minor_suspected=bool(urow.get("is_minor_suspected"))
                    )
                ):
                    await _finalize_task(
                        session,
                        task_id=task_id,
                        status="failed",
                        failure_reason="minor_or_user_notification_restricted",
                    )
                    stats["failed"] = 1
                    log.bind(task_id=task_id, user_id=user_id).warning(
                        "notification_sender_worker.minor_protection_blocked"
                    )
                    task_id = None
                    return stats

                chat_id = telegram_chat_id_from_external(urow.get("external_id"))
                if chat_id is None:
                    await _finalize_task(
                        session,
                        task_id=task_id,
                        status="failed",
                        failure_reason="no_telegram_chat_id",
                    )
                    stats["failed"] = 1
                    task_id = None
                    return stats

                if not settings.TELEGRAM_BOT_TOKEN:
                    await _finalize_task(
                        session,
                        task_id=task_id,
                        status="failed",
                        failure_reason="telegram_bot_token_missing",
                    )
                    stats["failed"] = 1
                    task_id = None
                    log.warning("notification_sender_worker.no_bot_token")
                    return stats

            finally:
                await session.execute(
                    text("SELECT pg_advisory_unlock(:k)"),
                    {"k": _ADVISORY_LOCK_KEY},
                )
                await session.commit()

        if task_id is None or chat_id is None or body is None:
            return stats

        mid = await send_telegram_text(
            chat_id=chat_id,
            text_content=body,
            trace_id=trace_id,
            parse_mode=None,
        )

        async with AsyncSessionLocal() as session2:
            if mid is not None:
                await _finalize_task(
                    session2, task_id=task_id, status="sent", failure_reason=None
                )
                stats["sent"] = 1
                log.bind(task_id=task_id, telegram_message_id=mid).info(
                    "notification_sender_worker.sent"
                )
            else:
                await _finalize_task(
                    session2,
                    task_id=task_id,
                    status="failed",
                    failure_reason="telegram_send_rejected",
                )
                stats["failed"] = 1
                log.bind(task_id=task_id).warning(
                    "notification_sender_worker.send_failed"
                )

    except Exception as exc:
        stats["error"] = f"{type(exc).__name__}:{exc}"
        log.bind(error_type=type(exc).__name__).exception(
            "notification_sender_worker.tick.error"
        )

    return stats


def start_scheduler() -> Optional[AsyncIOScheduler]:
    global _scheduler
    if not settings.NOTIFICATION_SENDER_ENABLED:
        logger.bind(component="notification_sender_worker").info(
            "notification_sender_worker.scheduler.disabled"
        )
        return None
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.bind(component="notification_sender_worker").warning(
            "notification_sender_worker.scheduler.no_bot_token"
        )
        return None
    if _scheduler is not None:
        return _scheduler

    interval = max(5, int(settings.NOTIFICATION_SENDER_POLL_SECONDS or 20))
    max_inst = max(
        1, int(settings.NOTIFICATION_SENDER_SCHEDULER_MAX_INSTANCES or 1)
    )
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        run_one_tick,
        trigger=IntervalTrigger(seconds=interval),
        id=JOB_ID,
        max_instances=max_inst,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.bind(
        component="notification_sender_worker",
        interval_s=interval,
        max_instances=max_inst,
    ).info("notification_sender_worker.scheduler.started")
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:
        logger.bind(component="notification_sender_worker").exception(
            "notification_sender_worker.scheduler.shutdown_error"
        )
    finally:
        _scheduler = None
        logger.bind(component="notification_sender_worker").info(
            "notification_sender_worker.scheduler.stopped"
        )
