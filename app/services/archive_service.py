"""Archive and premium chat trace service for P3-18/P3-19/P3-21."""

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

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger
except ModuleNotFoundError:
    AsyncIOScheduler = None  # type: ignore[assignment]
    IntervalTrigger = None  # type: ignore[assignment]

_ADVISORY_LOCK_KEY = 6_300_423
JOB_ID = "archive_worker_tick"

_scheduler: Optional[AsyncIOScheduler] = None


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


async def _claim_archive_task(session: AsyncSession) -> dict[str, Any] | None:
    """Claim one pending archive task."""
    row = (
        await session.execute(
            text(
                """
                WITH c AS (
                    SELECT id, user_id, external_user_id, metadata
                    FROM message_schedules
                    WHERE status = 'sent'
                      AND metadata->>'script_hit_id' IS NOT NULL
                      AND id NOT IN (
                          SELECT DISTINCT source_message_id::text::uuid
                          FROM conversation_script_hits
                          WHERE source_message_id IS NOT NULL
                      )
                    ORDER BY sent_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                SELECT c.id, c.user_id, c.external_user_id, c.metadata
                FROM c
                """
            )
        )
    ).mappings().first()
    if not row:
        return None
    await session.commit()
    return dict(row)


async def _create_archive_record(
    session: AsyncSession,
    conversation_id: str,
    message_id: str,
    script_hit_id: str,
    hook: str = "archive",
    user_level: str = "C",
    platform: str = "telegram",
    source_message_id: str | None = None,
    script_ids: list[str] | None = None,
    matched: bool = True,
    degradation: str | None = None,
    intent_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> str:
    """Create archive record in conversation_script_hits table."""
    result = await session.execute(
        text(
            """
            INSERT INTO conversation_script_hits (
                conversation_id, message_id, hook, script_hit_id,
                script_ids, matched, degradation, user_level, platform,
                intent_id, source_message_id, metadata, trace_id, created_at, updated_at
            ) VALUES (
                :conversation_id, :message_id, :hook, :script_hit_id,
                CAST(:script_ids AS jsonb), :matched, :degradation, :user_level, :platform,
                :intent_id, CAST(:source_message_id AS uuid), CAST(:metadata AS jsonb),
                :trace_id, NOW(), NOW()
            )
            RETURNING id
            """
        ),
        {
            "conversation_id": conversation_id,
            "message_id": message_id,
            "hook": hook,
            "script_hit_id": script_hit_id,
            "script_ids": _json_dumps(script_ids or ([script_hit_id] if script_hit_id else [])),
            "matched": matched,
            "degradation": degradation,
            "user_level": user_level,
            "platform": platform,
            "intent_id": intent_id,
            "source_message_id": source_message_id,
            "metadata": _json_dumps(metadata or {}),
            "trace_id": trace_id,
        }
    )
    archive_id = str(result.scalar())
    await session.commit()
    return archive_id


async def _get_message_details(
    session: AsyncSession,
    message_id: str,
) -> dict[str, Any] | None:
    """Get message details for archiving."""
    result = await session.execute(
        text(
            """
            SELECT
                m.id,
                m.conversation_id,
                m.sender_type,
                m.content,
                COALESCE(p.user_level, 'C') AS user_level,
                u.channel,
                m.created_at
            FROM messages m
            JOIN users u ON m.user_id = u.id
            LEFT JOIN user_profiles p ON p.user_id = u.id
            WHERE m.id = :message_id
            """
        ),
        {"message_id": message_id}
    )
    row = result.fetchone()
    if not row:
        return None
    return {
        "id": str(row[0]),
        "conversation_id": str(row[1]),
        "sender_type": row[2],
        "content": row[3],
        "user_level": row[4],
        "channel": row[5] or "telegram",
        "created_at": row[6],
    }


async def archive_message(
    conversation_id: str,
    message_id: str,
    script_hit_id: str,
    hook: str = "archive",
    user_level: str = "C",
    platform: str = "telegram",
    trace_id: Optional[str] = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Archive a message with script hit record (async, non-blocking).

    This function is designed to be called asynchronously without blocking the main chain.
    """
    async with AsyncSessionLocal() as session:
        try:
            archive_id = await _create_archive_record(
                session=session,
                conversation_id=conversation_id,
                message_id=message_id,
                script_hit_id=script_hit_id,
                hook=hook,
                user_level=user_level,
                platform=platform,
                metadata=metadata,
                trace_id=trace_id,
            )

            logger.bind(
                trace_id=trace_id,
                archive_id=archive_id,
                conversation_id=conversation_id,
                message_id=message_id,
                script_hit_id=script_hit_id,
            ).info("archive_service.archived")

            return archive_id

        except Exception as e:
            logger.bind(
                trace_id=trace_id,
                conversation_id=conversation_id,
                message_id=message_id,
            ).error(f"archive_service.archive_error: {e}")
            raise


async def archive_message_async(
    conversation_id: str,
    message_id: str,
    script_hit_id: str,
    hook: str = "archive",
    user_level: str = "C",
    platform: str = "telegram",
    trace_id: Optional[str] = None,
    metadata: dict[str, Any] | None = None,
) -> asyncio.Task:
    """Archive a message asynchronously without blocking.

    This creates a background task that will complete independently of the main chain.
    """
    async def _archive_task():
        try:
            await archive_message(
                conversation_id=conversation_id,
                message_id=message_id,
                script_hit_id=script_hit_id,
                hook=hook,
                user_level=user_level,
                platform=platform,
                trace_id=trace_id,
                metadata=metadata,
            )
        except Exception as e:
            logger.bind(
                trace_id=trace_id,
                conversation_id=conversation_id,
                message_id=message_id,
            ).error(f"archive_service.async_task_error: {e}")

    # Create background task without await
    task = asyncio.create_task(_archive_task())
    return task


async def run_one_tick(trace_id: Optional[str] = None) -> dict[str, Any]:
    """Process one pending archive task (for worker)."""
    trace_id = trace_id or f"archive-{int(datetime.utcnow().timestamp())}"
    log = logger.bind(component="archive_service", trace_id=trace_id)
    stats: dict[str, Any] = {
        "claimed": 0,
        "archived": 0,
        "failed": 0,
        "skipped_no_lock": 0,
        "error": None,
    }

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
                log.info("archive_service.tick.skip_no_lock")
                return stats

            try:
                # Claim one sent message with script_hit_id
                task = await _claim_archive_task(session)
                if not task:
                    log.info("archive_service.tick.empty")
                    return stats

                stats["claimed"] = 1
                source_message_id = str(task["id"])
                metadata = task.get("metadata") or {}
                if isinstance(metadata, str):
                    metadata = json.loads(metadata)
                message_id = metadata.get("message_id")
                conversation_id = metadata.get("conversation_id")
                script_hit_id = str(metadata["script_hit_id"])

                log.bind(
                    source_message_id=source_message_id,
                    conversation_id=conversation_id,
                    script_hit_id=script_hit_id,
                ).info("archive_service.tick.claimed")

                # Get message details
                if not conversation_id:
                    log.warning("archive_service.tick.no_conversation_id")
                    stats["failed"] = 1
                    return stats
                message_details = (
                    await _get_message_details(session, message_id)
                    if message_id else {}
                )

                # Create archive record
                archive_id = await _create_archive_record(
                    session=session,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    script_hit_id=script_hit_id,
                    hook="archive",
                    user_level=metadata.get("user_level") or message_details.get("user_level", "C"),
                    platform=metadata.get("platform") or message_details.get("channel", "telegram_real_user"),
                    source_message_id=source_message_id,
                    script_ids=metadata.get("script_ids") or [script_hit_id],
                    matched=True,
                    metadata=metadata,
                    trace_id=trace_id,
                )

                stats["archived"] = 1
                log.bind(
                    archive_id=archive_id,
                    message_id=message_id,
                ).info("archive_service.tick.archived")

            except Exception as e:
                log.error(f"archive_service.tick.error: {e}")
                stats["error"] = str(e)
                stats["failed"] = 1

    except Exception as e:
        log.error(f"archive_service.tick.outer_error: {e}")
        stats["error"] = str(e)

    return stats


def start_scheduler() -> None:
    """Start the archive worker scheduler."""
    global _scheduler
    if _scheduler is None:
        logger.warning("APScheduler not available, archive worker scheduler not started")
        return

    if _scheduler.running:
        logger.warning("Archive worker scheduler already running")
        return

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_one_tick,
        trigger=IntervalTrigger(
            seconds=getattr(settings, "ARCHIVE_WORKER_POLL_SECONDS", 30)
        ),
        id=JOB_ID,
        max_instances=getattr(settings, "ARCHIVE_WORKER_SCHEDULER_MAX_INSTANCES", 1),
    )
    _scheduler.start()
    logger.info("Archive worker scheduler started")


def shutdown_scheduler() -> None:
    """Shutdown the archive worker scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
        logger.info("Archive worker scheduler shutdown")


def get_scheduler_status() -> dict:
    """Get scheduler status."""
    return {
        "running": _scheduler is not None and _scheduler.running,
        "job_id": JOB_ID if _scheduler else None,
        "job_exists": _scheduler is not None and JOB_ID in _scheduler
        if _scheduler else False,
    }


async def get_conversation_script_hits(
    conversation_id: str,
    limit: int = 100,
    trace_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Get script hit records for a conversation."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT
                    id,
                    conversation_id,
                    message_id,
                    hook,
                    script_ids,
                    script_hit_id,
                    matched,
                    degradation,
                    user_level,
                    platform,
                    created_at,
                    updated_at
                FROM conversation_script_hits
                WHERE conversation_id = :conversation_id
                ORDER BY created_at ASC
                LIMIT :limit
                """
            ),
            {"conversation_id": conversation_id, "limit": limit}
        )
        rows = result.mappings().all()
        return [dict(row) for row in rows]


async def get_premium_chat_trace(
    conversation_id: str,
    limit: int = 100,
    trace_id: Optional[str] = None,
) -> dict[str, Any]:
    """Return S/A premium conversation messages plus script-hit trajectory."""
    async with AsyncSessionLocal() as session:
        conv = (
            await session.execute(
                text(
                    """
                    SELECT
                        c.id,
                        c.user_id,
                        c.channel,
                        c.state,
                        c.created_at,
                        c.updated_at,
                        COALESCE(p.user_level, 'C') AS user_level,
                        u.external_id,
                        u.nickname
                    FROM conversations c
                    JOIN users u ON c.user_id = u.id
                    LEFT JOIN user_profiles p ON p.user_id = u.id
                    WHERE c.id = :conversation_id
                    """
                ),
                {"conversation_id": conversation_id},
            )
        ).mappings().first()
        if not conv:
            return {
                "found": False,
                "eligible": False,
                "reason": "conversation_not_found",
                "conversation_id": conversation_id,
            }

        user_level = str(conv.get("user_level") or "")
        eligible = user_level in {"S", "A"}

        messages = (
            await session.execute(
                text(
                    """
                    SELECT id, sender_type, sender_id, content, content_type, created_at
                    FROM messages
                    WHERE conversation_id = :conversation_id
                    ORDER BY created_at ASC
                    LIMIT :limit
                    """
                ),
                {"conversation_id": conversation_id, "limit": limit},
            )
        ).mappings().all()

        hits = await get_conversation_script_hits(
            conversation_id=conversation_id,
            limit=limit * 8,
            trace_id=trace_id,
        )
        hooks_seen = {str(hit["hook"]) for hit in hits}
        missing_hooks = [
            hook for hook in (
                "inbound",
                "consumption",
                "probe",
                "grading",
                "reply",
                "operator",
                "outbound",
                "archive",
            )
            if hook not in hooks_seen
        ]

        return {
            "found": True,
            "eligible": eligible,
            "reason": None if eligible else "user_level_not_s_or_a",
            "conversation": dict(conv),
            "messages": [dict(row) for row in messages],
            "script_hits": hits,
            "traceability": {
                "total_hits": len(hits),
                "hooks_seen": sorted(hooks_seen),
                "missing_hooks": missing_hooks,
                "complete_8_hooks": len(missing_hooks) == 0,
                "all_steps_have_match_or_degradation": all(
                    bool(hit.get("matched")) or bool(hit.get("degradation"))
                    for hit in hits
                ),
            },
        }
