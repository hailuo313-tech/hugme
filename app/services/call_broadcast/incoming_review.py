"""Operator accept/reject for inbound calls after automated video sequence."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import AsyncSessionLocal
from services.call_broadcast.incoming_review_registry import (
    PendingIncomingReview,
    get_pending_review,
    list_expired_job_ids,
    pop_pending_review,
    register_pending_review,
)
from services.call_broadcast.jobs import (
    count_active_calls_for_account,
    create_inbound_operator_review_job,
    finalize_job,
    mark_job_streaming,
    resolve_inbound_call_context,
)
from services.call_broadcast.session import reject_inbound_call, run_call_broadcast


async def _gated_reject_inbound_call(*, account_id, chat_id, trace_id):
    from services.telegram_command_gateway import submit_telegram_command

    async def _legacy():
        return await reject_inbound_call(
            account_id=account_id,
            chat_id=chat_id,
            trace_id=trace_id,
        )

    return await submit_telegram_command(
        command_type="reject_call",
        account_id=str(account_id),
        legacy_execute=_legacy,
        payload={"chat_id": chat_id},
        trace_id=trace_id,
    )


def inbound_call_should_auto_answer(
    *,
    completed_playbacks: int,
    recorded_attempts: int,
    operator_review_attempts: int = 0,
    auto_answer_threshold: int | None = None,
) -> bool:
    """True when the next inbound ring may auto-answer with play_sequence 1/2."""
    threshold = (
        int(auto_answer_threshold)
        if auto_answer_threshold is not None
        else int(getattr(settings, "CALL_BROADCAST_INBOUND_MANUAL_AFTER", 2))
    )
    next_playback_number = completed_playbacks + 1
    if next_playback_number > threshold:
        return False
    # Only successful playbacks advance the first/second video sequence.
    # Failed auto answers and reviews created from those failures are retryable.
    return True


def inbound_call_requires_operator_review(
    *,
    completed_playbacks: int,
    recorded_attempts: int,
    operator_review_attempts: int = 0,
    auto_answer_threshold: int | None = None,
) -> bool:
    """True after the auto-answer videos have already played successfully."""
    return not inbound_call_should_auto_answer(
        completed_playbacks=completed_playbacks,
        recorded_attempts=recorded_attempts,
        operator_review_attempts=operator_review_attempts,
        auto_answer_threshold=auto_answer_threshold,
    )


async def queue_inbound_operator_review(
    db: AsyncSession,
    *,
    account_id: str,
    chat_id: int,
    access_hash: int | None,
    trace_id: str,
) -> str | None:
    existing = (
        await db.execute(
            text(
                """
                SELECT id::text
                FROM call_broadcast_jobs
                WHERE chat_id = :chat_id
                  AND status = 'pending_operator'
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"chat_id": int(chat_id)},
        )
    ).first()
    if existing is not None:
        mapping = dict(existing._mapping)
        return str(mapping.get("id") or existing[0])

    call_ctx = await resolve_inbound_call_context(db, chat_id)
    inbound_call_number = int(call_ctx["inbound_call_number"])
    call_attempt_number = int(call_ctx["call_attempt_number"])
    job_id = await create_inbound_operator_review_job(
        db,
        chat_id=chat_id,
        account_id=account_id,
        trace_id=trace_id,
        telegram_access_hash=access_hash,
        inbound_call_number=inbound_call_number,
        call_attempt_number=call_attempt_number,
    )
    if not job_id:
        return None
    ttl = int(getattr(settings, "CALL_BROADCAST_INBOUND_REVIEW_TTL_SECONDS", 90))
    register_pending_review(
        job_id=job_id,
        account_id=account_id,
        chat_id=chat_id,
        access_hash=access_hash,
        trace_id=trace_id,
        inbound_call_number=inbound_call_number,
        ttl_seconds=ttl,
    )
    return job_id


async def _wait_operator_job_progress(
    job_id: str, *, timeout_seconds: float = 20
) -> str | None:
    """Wait until a queued accept leaves pending_operator, or time out."""
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    last_status = "pending_operator"
    while time.monotonic() < deadline:
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    text(
                        """
                        SELECT status
                        FROM call_broadcast_jobs
                        WHERE id = CAST(:job_id AS uuid)
                        LIMIT 1
                        """
                    ),
                    {"job_id": job_id},
                )
            ).first()
        last_status = str(row[0]) if row is not None else None
        if last_status and last_status != "pending_operator":
            return last_status
        await asyncio.sleep(0.3)
    return last_status


async def _load_video_asset(db: AsyncSession, video_asset_id: str) -> dict[str, Any] | None:
    row = (
        await db.execute(
            text(
                """
                SELECT id, title, file_path, duration_seconds, play_sequence
                FROM video_broadcast_assets
                WHERE id = CAST(:asset_id AS uuid) AND status = 'active'
                LIMIT 1
                """
            ),
            {"asset_id": video_asset_id},
        )
    ).first()
    if row is None:
        return None
    data = row._mapping if hasattr(row, "_mapping") else row
    return dict(data)


async def _load_operator_job(db: AsyncSession, job_id: str) -> dict[str, Any] | None:
    row = (
        await db.execute(
            text(
                """
                SELECT id::text, chat_id, account_id::text, status, trace_id, metadata,
                       trigger_source, created_at
                FROM call_broadcast_jobs
                WHERE id = CAST(:job_id AS uuid)
                  AND status = 'pending_operator'
                LIMIT 1
                """
            ),
            {"job_id": job_id},
        )
    ).first()
    if row is None:
        return None
    return dict(row._mapping)


def _metadata_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _review_ttl_seconds(trigger_source: str) -> int:
    if trigger_source == "inbound_keyword_review":
        return int(getattr(settings, "CALL_BROADCAST_KEYWORD_REVIEW_TTL_SECONDS", 600))
    return int(getattr(settings, "CALL_BROADCAST_INBOUND_REVIEW_TTL_SECONDS", 90))


def _created_at_epoch(created_at: Any) -> float | None:
    """Unix seconds for DB timestamps. Naive values are treated as UTC."""
    if created_at is None:
        return None
    if isinstance(created_at, datetime):
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return created_at.timestamp()
    if hasattr(created_at, "timestamp"):
        return float(created_at.timestamp())
    return None


def _review_is_expired(*, trigger_source: str, created_at: Any) -> bool:
    """Text keyword requests stay actionable while DB row is pending_operator."""
    if trigger_source == "inbound_keyword_review":
        return False
    created_epoch = _created_at_epoch(created_at)
    if created_epoch is None:
        return False
    ttl = _review_ttl_seconds(trigger_source)
    return created_epoch + ttl <= time.time()


def _remaining_review_seconds(*, trigger_source: str, created_at: Any) -> int:
    ttl = _review_ttl_seconds(trigger_source)
    if trigger_source == "inbound_keyword_review":
        return ttl
    created_epoch = _created_at_epoch(created_at)
    if created_epoch is None:
        return ttl
    return max(0, int(created_epoch + ttl - time.time()))


async def hydrate_pending_review_from_job(
    db: AsyncSession,
    job_id: str,
    *,
    allow_expired: bool = False,
) -> PendingIncomingReview | None:
    """Re-register in-memory review after API restart (DB row still pending)."""
    review = get_pending_review(job_id, include_expired=allow_expired)
    if review is not None:
        return review

    job = await _load_operator_job(db, job_id)
    if job is None:
        return None

    metadata = _metadata_dict(job.get("metadata"))
    trigger_source = str(job.get("trigger_source") or "")
    remaining = _remaining_review_seconds(
        trigger_source=trigger_source,
        created_at=job.get("created_at"),
    )
    if remaining <= 0:
        if not allow_expired:
            return None
        remaining = 30

    access_hash_raw = metadata.get("telegram_access_hash")
    access_hash = int(access_hash_raw) if access_hash_raw is not None else None
    call_ctx = await resolve_inbound_call_context(db, int(job["chat_id"]))
    inbound_call_number = int(call_ctx["inbound_call_number"])

    return register_pending_review(
        job_id=job_id,
        account_id=str(job["account_id"]),
        chat_id=int(job["chat_id"]),
        access_hash=access_hash,
        trace_id=str(job.get("trace_id") or job_id),
        inbound_call_number=inbound_call_number,
        ttl_seconds=remaining,
    )


async def accept_operator_review(
    *,
    job_id: str,
    video_asset_id: str,
    operator_id: str,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        review = await hydrate_pending_review_from_job(db, job_id, allow_expired=True)
        if review is None:
            return {"ok": False, "reason": "review_expired_or_missing"}

        job = await _load_operator_job(db, job_id)
        if job is None:
            pop_pending_review(job_id)
            return {"ok": False, "reason": "job_not_pending"}

        active_calls = await count_active_calls_for_account(db, UUID(str(job["account_id"])))
        if active_calls > 0:
            return {"ok": False, "reason": "account_busy_on_call"}

        asset = await _load_video_asset(db, video_asset_id)
        if asset is None:
            return {"ok": False, "reason": "video_asset_not_found"}

        duration = int(
            asset.get("duration_seconds")
            or getattr(settings, "CALL_BROADCAST_DEFAULT_DURATION_SECONDS", 30)
        )

        from services.runtime_ownership import get_account_ownership
        from services.telegram_command_gateway import submit_telegram_command

        ownership = await get_account_ownership(str(job["account_id"]), db)
        if ownership.is_runtime:
            async def _noop():
                return None

            gated = await submit_telegram_command(
                command_type="answer_call",
                account_id=str(job["account_id"]),
                legacy_execute=_noop,
                payload={
                    "job_id": job_id,
                    "video_asset_id": video_asset_id,
                    "operator_id": operator_id,
                    "chat_id": review.chat_id,
                    "video_path": str(asset.get("file_path") or ""),
                    "duration_seconds": duration,
                    "access_hash": review.access_hash,
                    "trace_id": str(job.get("trace_id") or job_id),
                },
                idempotency_key=f"answer_call:{job_id}",
                trace_id=str(job.get("trace_id") or job_id),
            )
            if not gated.accepted_not_sent:
                return {
                    "ok": False,
                    "reason": gated.reason or "telegram_gateway_rejected",
                }
            await db.execute(
                text(
                    """
                    UPDATE call_broadcast_jobs
                    SET video_asset_id = CAST(:video_asset_id AS uuid),
                        metadata = metadata || CAST(:meta_patch AS jsonb),
                        updated_at = NOW()
                    WHERE id = CAST(:job_id AS uuid)
                      AND status = 'pending_operator'
                    """
                ),
                {
                    "job_id": job_id,
                    "video_asset_id": video_asset_id,
                    "meta_patch": json.dumps(
                        {
                            "operator_id": operator_id,
                            "accepted": True,
                            "queued_for_runtime": True,
                            "command_id": gated.command_id,
                            "video_asset_id": video_asset_id,
                        },
                        ensure_ascii=False,
                    ),
                },
            )
            await db.commit()
            pop_pending_review(job_id)
            answered = await _wait_operator_job_progress(
                job_id, timeout_seconds=20
            )
            if answered in {"streaming", "completed"}:
                return {
                    "ok": True,
                    "job_id": job_id,
                    "status": answered,
                    "executed": True,
                    "command_id": gated.command_id,
                }
            if answered in {"failed", "cancelled"}:
                return {
                    "ok": False,
                    "reason": f"runtime_{answered}",
                    "command_id": gated.command_id,
                }
            return {
                "ok": True,
                "job_id": job_id,
                "status": "accepted",
                "executed": False,
                "command_id": gated.command_id,
            }

    pop_pending_review(job_id)
    trace_id = review.trace_id
    log = logger.bind(
        component="call_broadcast_incoming_review",
        trace_id=trace_id,
        job_id=job_id,
        operator_id=operator_id,
        chat_id=review.chat_id,
    )

    try:
        async with AsyncSessionLocal() as db:
            await mark_job_streaming(db, job_id)
            await db.execute(
                text(
                    """
                    UPDATE call_broadcast_jobs
                    SET video_asset_id = CAST(:video_asset_id AS uuid),
                        metadata = metadata || CAST(:meta_patch AS jsonb),
                        updated_at = NOW()
                    WHERE id = CAST(:job_id AS uuid)
                    """
                ),
                {
                    "job_id": job_id,
                    "video_asset_id": video_asset_id,
                    "meta_patch": json.dumps(
                        {
                            "operator_id": operator_id,
                            "accepted": True,
                            "video_asset_id": video_asset_id,
                        },
                        ensure_ascii=False,
                    ),
                },
            )
            await db.commit()

        from services.telegram_command_gateway import submit_telegram_command

        async def _legacy_answer():
            return await run_call_broadcast(
                account_id=UUID(review.account_id),
                chat_id=int(review.chat_id),
                video_path=str(asset["file_path"]),
                duration_seconds=duration,
                trace_id=trace_id,
                telegram_access_hash=review.access_hash,
                job_id=str(job_id),
            )

        gated = await submit_telegram_command(
            command_type="answer_call",
            account_id=str(review.account_id),
            legacy_execute=_legacy_answer,
            payload={"job_id": job_id, "chat_id": review.chat_id},
            trace_id=trace_id,
        )
        if gated.accepted_not_sent:
            return {
                "ok": True,
                "job_id": job_id,
                "status": "accepted",
                "executed": False,
                "command_id": gated.command_id,
            }
        if not gated.executed:
            raise RuntimeError(gated.reason or "telegram_gateway_rejected")
        playback = gated.value

        async with AsyncSessionLocal() as db:
            await finalize_job(
                db,
                job_id=job_id,
                status="completed",
                playback_result=playback,
            )
            await db.commit()

        log.info("call_broadcast.incoming_review.accepted")
        return {"ok": True, "job_id": job_id, "status": "completed"}
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("call_broadcast.incoming_review.accept_failed")
        async with AsyncSessionLocal() as db:
            await finalize_job(
                db,
                job_id=job_id,
                status="failed",
                failure_reason=str(exc)[:500],
            )
            await db.commit()
        return {"ok": False, "reason": type(exc).__name__}


async def reject_operator_review(
    *,
    job_id: str,
    operator_id: str,
) -> dict[str, Any]:
    review = pop_pending_review(job_id)
    if review is None:
        async with AsyncSessionLocal() as db:
            job = await _load_operator_job(db, job_id)
            if job is None:
                return {"ok": False, "reason": "job_not_pending"}
            review_chat = int(job["chat_id"])
            review_account = str(job["account_id"])
            review_trace = str(job.get("trace_id") or "")
        await _gated_reject_inbound_call(
            account_id=UUID(review_account),
            chat_id=review_chat,
            trace_id=review_trace,
        )
        async with AsyncSessionLocal() as db:
            await finalize_job(
                db,
                job_id=job_id,
                status="cancelled",
                failure_reason="operator_rejected_after_expiry",
            )
            await db.commit()
        return {"ok": True, "job_id": job_id, "status": "cancelled"}

    log = logger.bind(
        component="call_broadcast_incoming_review",
        trace_id=review.trace_id,
        job_id=job_id,
        operator_id=operator_id,
        chat_id=review.chat_id,
    )
    try:
        await _gated_reject_inbound_call(
            account_id=UUID(review.account_id),
            chat_id=int(review.chat_id),
            trace_id=review.trace_id,
        )
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning(
            "call_broadcast.incoming_review.reject_call_failed"
        )

    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                """
                UPDATE call_broadcast_jobs
                SET metadata = metadata || CAST(:meta_patch AS jsonb),
                    updated_at = NOW()
                WHERE id = CAST(:job_id AS uuid)
                """
            ),
            {
                "job_id": job_id,
                "meta_patch": json.dumps(
                    {"operator_id": operator_id, "accepted": False},
                    ensure_ascii=False,
                ),
            },
        )
        await finalize_job(
            db,
            job_id=job_id,
            status="cancelled",
            failure_reason="operator_rejected",
        )
        await db.commit()

    log.info("call_broadcast.incoming_review.rejected")
    return {"ok": True, "job_id": job_id, "status": "cancelled"}


async def list_stale_operator_review_job_ids(db: AsyncSession) -> list[str]:
    """Pending inbound reviews left in DB after the operator grace window.

    Memory TTL (default 90s) still expires the live ring. DB-only leftovers
    wait longer so a just-timeout card can still be answered from admin.
    """
    ttl = int(getattr(settings, "CALL_BROADCAST_INBOUND_REVIEW_TTL_SECONDS", 90))
    zombie_after = max(ttl * 2, 300)
    rows = (
        await db.execute(
            text(
                """
                SELECT id::text
                FROM call_broadcast_jobs
                WHERE status = 'pending_operator'
                  AND COALESCE(trigger_source, '') <> 'inbound_keyword_review'
                  AND created_at < NOW() - make_interval(secs => :zombie_after)
                ORDER BY created_at ASC
                LIMIT 50
                """
            ),
            {"zombie_after": zombie_after},
        )
    ).fetchall()
    return [str(row[0]) for row in rows]


async def cancel_stale_operator_review(
    job_id: str,
    *,
    reject_telegram: bool = False,
) -> bool:
    """Mark a stale inbound review cancelled. Telegram reject is opt-in.

    Zombie DB rows must not call hang-up: empty-arg fallbacks on the account
    wrapper can hit a different live incoming call.
    """
    try:
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    text(
                        """
                        SELECT chat_id, account_id::text, trace_id, trigger_source, metadata
                        FROM call_broadcast_jobs
                        WHERE id = CAST(:job_id AS uuid)
                          AND status = 'pending_operator'
                        LIMIT 1
                        """
                    ),
                    {"job_id": job_id},
                )
            ).first()
            if row is None:
                return False
            mapping = dict(row._mapping)
            trigger_source = str(mapping.get("trigger_source") or "")
            meta = _metadata_dict(mapping.get("metadata"))
            if meta.get("queued_for_runtime") or meta.get("accepted"):
                return False
            # Text "video chat" requests stay in DB until an operator acts; do not auto-cancel.
            if trigger_source == "inbound_keyword_review":
                await hydrate_pending_review_from_job(db, job_id)
                return False
            if reject_telegram:
                try:
                    await _gated_reject_inbound_call(
                        account_id=UUID(str(mapping["account_id"])),
                        chat_id=int(mapping["chat_id"]),
                        trace_id=str(mapping.get("trace_id") or ""),
                    )
                except Exception as exc:
                    logger.bind(
                        job_id=job_id,
                        error_type=type(exc).__name__,
                    ).warning("call_broadcast.incoming_review.expire_reject_failed")
            await finalize_job(
                db,
                job_id=job_id,
                status="cancelled",
                failure_reason="review_expired",
            )
            await db.commit()
        pop_pending_review(job_id)
        logger.bind(job_id=job_id).info("call_broadcast.incoming_review.expired")
        return True
    except Exception as exc:
        logger.bind(job_id=job_id, error_type=type(exc).__name__).warning(
            "call_broadcast.incoming_review.expire_failed"
        )
        return False


async def expire_stale_operator_reviews() -> int:
    memory_ids = set(list_expired_job_ids())
    async with AsyncSessionLocal() as db:
        db_ids = set(await list_stale_operator_review_job_ids(db))
    cancelled = 0
    for job_id in memory_ids:
        if await cancel_stale_operator_review(job_id, reject_telegram=True):
            cancelled += 1
    for job_id in db_ids - memory_ids:
        if await cancel_stale_operator_review(job_id, reject_telegram=False):
            cancelled += 1
    return cancelled


async def restore_pending_reviews(db: AsyncSession) -> dict[str, int]:
    """Rebuild in-memory review registry from pending_operator rows.

    Memory remains the live working copy after restore. DB is the restart
    source of truth. Failures are counted, not raised.
    """
    restored = 0
    skipped = 0
    rows = (
        await db.execute(
            text(
                """
                SELECT id::text
                FROM call_broadcast_jobs
                WHERE status = 'pending_operator'
                ORDER BY created_at ASC
                LIMIT 200
                """
            )
        )
    ).fetchall()
    for row in rows:
        mapping = dict(row._mapping) if hasattr(row, "_mapping") else {"id": row[0]}
        job_id = str(mapping.get("id") or row[0])
        review = await hydrate_pending_review_from_job(db, job_id)
        if review is None:
            skipped += 1
        else:
            restored += 1
    return {"restored": restored, "skipped": skipped, "total": restored + skipped}


async def restore_pending_reviews_from_db() -> dict[str, Any]:
    try:
        async with AsyncSessionLocal() as db:
            stats = await restore_pending_reviews(db)
        logger.bind(**stats).info("call_broadcast.incoming_review.restored_from_db")
        return {"ok": True, **stats}
    except Exception as exc:
        logger.bind(error_type=type(exc).__name__).warning(
            "call_broadcast.incoming_review.restore_failed"
        )
        return {
            "ok": False,
            "restored": 0,
            "skipped": 0,
            "total": 0,
            "error": type(exc).__name__,
        }


def spawn_accept_operator_review(**kwargs: Any) -> None:
    asyncio.create_task(accept_operator_review(**kwargs))
