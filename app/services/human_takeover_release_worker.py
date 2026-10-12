"""Background worker: release idle human takeovers and queue AI catch-up replies."""

from __future__ import annotations

import time
from typing import Any, Optional

import redis.asyncio as aioredis
from loguru import logger
from sqlalchemy import text

from core.config import settings
from core.database import AsyncSessionLocal
from services.human_takeover_gate import (
    DELIVERY_MODE,
    MESSAGE_TYPE,
    list_idle_human_takeover_candidates,
    release_human_takeover_to_ai,
)
from services.llm_orchestrator import LLMOrchestratorError, generate_reply
from services.ai_message_limit import AIMessageLimitReached, handoff_t1_timeout_candidates
from services.message_schedule_service import add_scheduled_message
from services.post_release_ai_followup import schedule_post_release_ai_checks

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger
except ModuleNotFoundError:
    AsyncIOScheduler = None  # type: ignore[assignment]
    IntervalTrigger = None  # type: ignore[assignment]

_ADVISORY_LOCK_KEY = 6_300_422
_T1_TIMEOUT_LOCK_KEY = 6_300_424
JOB_ID = "human_takeover_release_tick"
_scheduler: Optional[AsyncIOScheduler] = None
_redis_client = None


def _telegram_chat_id_from_external(external_id: str | None) -> int | None:
    if not external_id:
        return None
    raw = external_id[3:] if external_id.startswith("tg_") else external_id
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


async def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL, encoding="utf-8", decode_responses=True
        )
    return _redis_client


async def _already_queued(db, conversation_id: str) -> bool:
    row = (
        await db.execute(
            text(
                """
                SELECT 1
                FROM message_schedules ms
                WHERE ms.metadata->>'delivery_mode' = :delivery_mode
                  AND ms.metadata->>'conversation_id' = :conversation_id
                  AND ms.status IN ('pending', 'sending')
                LIMIT 1
                """
            ),
            {
                "delivery_mode": DELIVERY_MODE,
                "conversation_id": conversation_id,
            },
        )
    ).fetchone()
    return row is not None


async def run_one_tick(trace_id: str | None = None) -> dict[str, Any]:
    trace_id = trace_id or f"hto-{int(time.time())}"
    log = logger.bind(component="human_takeover_release_worker", trace_id=trace_id)
    stats: dict[str, Any] = {
        "candidates": 0,
        "released": 0,
        "queued": 0,
        "followup_checks_queued": 0,
        "t1_timeout_handoffs": 0,
        "skipped_no_lock": 0,
        "errors": 0,
    }

    if not settings.HUMAN_TAKEOVER_RELEASE_WORKER_ENABLED:
        return stats

    try:
        async with AsyncSessionLocal() as t1_session:
            got_t1 = (
                await t1_session.execute(
                    text("SELECT pg_try_advisory_lock(:k)"),
                    {"k": _T1_TIMEOUT_LOCK_KEY},
                )
            ).scalar()
            if got_t1:
                try:
                    handed = await handoff_t1_timeout_candidates(
                        t1_session, trace_id=trace_id
                    )
                    stats["t1_timeout_handoffs"] = handed
                    if handed:
                        await t1_session.commit()
                        log.bind(handed=handed).info(
                            "human_takeover_release_worker.t1_timeout_handoff"
                        )
                finally:
                    await t1_session.execute(
                        text("SELECT pg_advisory_unlock(:k)"),
                        {"k": _T1_TIMEOUT_LOCK_KEY},
                    )
            else:
                log.info("human_takeover_release_worker.t1_timeout_skip_no_lock")

        async with AsyncSessionLocal() as session:
            got = (
                await session.execute(
                    text("SELECT pg_try_advisory_lock(:k)"),
                    {"k": _ADVISORY_LOCK_KEY},
                )
            ).scalar()
            if not got:
                stats["skipped_no_lock"] = 1
                log.info("human_takeover_release_worker.skip_no_lock")
                return stats

            try:
                candidates = await list_idle_human_takeover_candidates(session)
                stats["candidates"] = len(candidates)
                if not candidates:
                    log.info("human_takeover_release_worker.tick.empty")
                    return stats

                redis = await _get_redis()
                for row in candidates:
                    conversation_id = str(row["conversation_id"])
                    user_id = str(row["user_id"])
                    if await _already_queued(session, conversation_id):
                        continue

                    released = await release_human_takeover_to_ai(
                        session,
                        conversation_id,
                        reason="idle_timeout_worker",
                    )
                    if not released:
                        continue
                    stats["released"] += 1
                    await session.commit()
                    stats["followup_checks_queued"] += await schedule_post_release_ai_checks(
                        session,
                        conversation_id=conversation_id,
                        source="human_takeover_release_worker",
                        operator_id=None,
                        trace_id=trace_id,
                    )
                    await session.commit()

                    user_text = str(row.get("last_user_text") or "").strip()
                    if not user_text:
                        continue

                    try:
                        async with AsyncSessionLocal() as reply_db:
                            reply_text = await generate_reply(
                                user_id=user_id,
                                conversation_id=conversation_id,
                                user_text=user_text,
                                trace_id=trace_id,
                                redis=redis,
                                db=reply_db,
                                trigger_message_id=row.get("last_user_msg_id"),
                            )
                    except AIMessageLimitReached as exc:
                        log.bind(
                            conversation_id=conversation_id,
                            reason=str(exc),
                        ).info("human_takeover_release_worker.ai_limit")
                        continue
                    except LLMOrchestratorError as exc:
                        log.bind(
                            conversation_id=conversation_id,
                            reason=str(exc),
                        ).warning("human_takeover_release_worker.orchestrator_failed")
                        stats["errors"] += 1
                        continue

                    external_user_id = str(row.get("external_user_id") or "")
                    chat_id = _telegram_chat_id_from_external(external_user_id)
                    account_id = row.get("telegram_account_id")
                    metadata = {
                        "delivery_mode": DELIVERY_MODE,
                        "conversation_id": conversation_id,
                        "source": "human_takeover_release_worker",
                    }
                    await add_scheduled_message(
                        user_id=user_id,
                        external_user_id=external_user_id,
                        message_type=MESSAGE_TYPE,
                        content=reply_text,
                        platform=str(row.get("platform") or "telegram_real_user"),
                        account_id=str(account_id) if account_id else None,
                        chat_id=chat_id,
                        priority=120,
                        metadata=metadata,
                        trace_id=trace_id,
                    )
                    stats["queued"] += 1
                    log.bind(
                        conversation_id=conversation_id,
                        user_id=user_id,
                    ).info("human_takeover_release_worker.reply_queued")
            finally:
                await session.execute(
                    text("SELECT pg_advisory_unlock(:k)"),
                    {"k": _ADVISORY_LOCK_KEY},
                )
    except Exception as exc:
        stats["errors"] += 1
        log.bind(error_type=type(exc).__name__).exception(
            "human_takeover_release_worker.tick_failed"
        )

    return stats


def start_scheduler() -> Optional[AsyncIOScheduler]:
    global _scheduler
    if AsyncIOScheduler is None or IntervalTrigger is None:
        return None
    if not settings.HUMAN_TAKEOVER_RELEASE_WORKER_ENABLED:
        return None
    if _scheduler is not None:
        return _scheduler

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        run_one_tick,
        IntervalTrigger(seconds=max(15, settings.HUMAN_TAKEOVER_RELEASE_POLL_SECONDS)),
        id=JOB_ID,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("human_takeover_release_worker.scheduler_started")
    return scheduler
