"""Operator accept/reject for inbound calls after automated video sequence."""

from __future__ import annotations

import asyncio
import json
import time
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
    count_completed_inbound_calls_for_chat,
    create_inbound_operator_review_job,
    finalize_job,
    mark_job_streaming,
)
from services.call_broadcast.session import reject_inbound_call, run_call_broadcast


def inbound_call_requires_operator_review(completed_inbound_count: int) -> bool:
    """True when the next inbound call exceeds automated auto-answer count (default: 2nd call onward)."""
    threshold = int(getattr(settings, "CALL_BROADCAST_INBOUND_MANUAL_AFTER", 1))
    return (completed_inbound_count + 1) > threshold


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

    completed = await count_completed_inbound_calls_for_chat(db, chat_id)
    inbound_call_number = completed + 1
    job_id = await create_inbound_operator_review_job(
        db,
        chat_id=chat_id,
        account_id=account_id,
        trace_id=trace_id,
        telegram_access_hash=access_hash,
        inbound_call_number=inbound_call_number,
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


def _review_is_expired(*, trigger_source: str, created_at: Any) -> bool:
    """Text keyword requests stay actionable while DB row is pending_operator."""
    if trigger_source == "inbound_keyword_review":
        return False
    if created_at is None or not hasattr(created_at, "timestamp"):
        return False
    ttl = _review_ttl_seconds(trigger_source)
    return created_at.timestamp() + ttl <= time.time()


async def hydrate_pending_review_from_job(
    db: AsyncSession,
    job_id: str,
) -> PendingIncomingReview | None:
    """Re-register in-memory review after API restart (DB row still pending)."""
    review = get_pending_review(job_id)
    if review is not None:
        return review

    job = await _load_operator_job(db, job_id)
    if job is None:
        return None

    metadata = _metadata_dict(job.get("metadata"))
    trigger_source = str(job.get("trigger_source") or "")
    if _review_is_expired(trigger_source=trigger_source, created_at=job.get("created_at")):
        return None

    ttl = _review_ttl_seconds(trigger_source)
    created_at = job.get("created_at")
    if trigger_source == "inbound_keyword_review":
        remaining = ttl
    elif created_at is not None and hasattr(created_at, "timestamp"):
        expires_at = created_at.timestamp() + ttl
        remaining = max(30, int(expires_at - time.time()))
    else:
        remaining = ttl

    access_hash_raw = metadata.get("telegram_access_hash")
    access_hash = int(access_hash_raw) if access_hash_raw is not None else None
    inbound_call_number = int(metadata.get("inbound_call_number") or 2)

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
        review = await hydrate_pending_review_from_job(db, job_id)
        if review is None:
            return {"ok": False, "reason": "review_expired_or_missing"}

        job = await _load_operator_job(db, job_id)
        if job is None:
            pop_pending_review(job_id)
            return {"ok": False, "reason": "job_not_pending"}

        asset = await _load_video_asset(db, video_asset_id)
        if asset is None:
            return {"ok": False, "reason": "video_asset_not_found"}

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

        duration = int(
            asset.get("duration_seconds")
            or getattr(settings, "CALL_BROADCAST_DEFAULT_DURATION_SECONDS", 30)
        )
        await run_call_broadcast(
            account_id=UUID(review.account_id),
            chat_id=int(review.chat_id),
            video_path=str(asset["file_path"]),
            duration_seconds=duration,
            trace_id=trace_id,
            telegram_access_hash=review.access_hash,
        )

        async with AsyncSessionLocal() as db:
            await finalize_job(db, job_id=job_id, status="completed")
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
        await reject_inbound_call(
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
        await reject_inbound_call(
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


async def expire_stale_operator_reviews() -> int:
    expired_ids = list_expired_job_ids()
    if not expired_ids:
        return 0

    for job_id in expired_ids:
        try:
            async with AsyncSessionLocal() as db:
                row = (
                    await db.execute(
                        text(
                            """
                            SELECT chat_id, account_id::text, trace_id
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
                    continue
                mapping = dict(row._mapping)
                await reject_inbound_call(
                    account_id=UUID(str(mapping["account_id"])),
                    chat_id=int(mapping["chat_id"]),
                    trace_id=str(mapping.get("trace_id") or ""),
                )
                await finalize_job(
                    db,
                    job_id=job_id,
                    status="cancelled",
                    failure_reason="review_expired",
                )
                await db.commit()
            logger.bind(job_id=job_id).info("call_broadcast.incoming_review.expired")
        except Exception as exc:
            logger.bind(job_id=job_id, error_type=type(exc).__name__).warning(
                "call_broadcast.incoming_review.expire_failed"
            )
    return len(expired_ids)


def spawn_accept_operator_review(**kwargs: Any) -> None:
    asyncio.create_task(accept_operator_review(**kwargs))
