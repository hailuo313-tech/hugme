"""Persistence helpers for call_broadcast_jobs and video assets."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from services.call_broadcast.keywords import TEST_IMMEDIATE_VIDEO_CALL_CODES


def _row_mapping(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    data = row._mapping if hasattr(row, "_mapping") else row
    return dict(data)


async def resolve_default_video_asset(db: AsyncSession) -> dict[str, Any] | None:
    configured_id = getattr(settings, "CALL_BROADCAST_DEFAULT_VIDEO_ASSET_ID", None)
    if configured_id:
        row = (
            await db.execute(
                text(
                    """
                    SELECT id, title, file_path, duration_seconds, ffmpeg_profile
                    FROM video_broadcast_assets
                    WHERE id = CAST(:asset_id AS uuid) AND status = 'active'
                    LIMIT 1
                    """
                ),
                {"asset_id": str(configured_id)},
            )
        ).first()
        if row is not None:
            return _row_mapping(row)

    default_path = str(getattr(settings, "CALL_BROADCAST_DEFAULT_VIDEO_PATH", "") or "").strip()
    if default_path:
        row = (
            await db.execute(
                text(
                    """
                    SELECT id, title, file_path, duration_seconds, ffmpeg_profile
                    FROM video_broadcast_assets
                    WHERE file_path = :file_path AND status = 'active'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"file_path": default_path},
            )
        ).first()
        if row is not None:
            return _row_mapping(row)
        return {
            "id": None,
            "title": "configured_default",
            "file_path": default_path,
            "duration_seconds": getattr(settings, "CALL_BROADCAST_DEFAULT_DURATION_SECONDS", 30),
            "ffmpeg_profile": {},
        }

    row = (
        await db.execute(
            text(
                """
                SELECT id, title, file_path, duration_seconds, ffmpeg_profile
                FROM video_broadcast_assets
                WHERE status = 'active'
                ORDER BY created_at ASC
                LIMIT 1
                """
            )
        )
    ).first()
    return _row_mapping(row) if row is not None else None


INBOUND_PLAY_SEQUENCE_MAX = 3


async def count_completed_inbound_calls_for_chat(db: AsyncSession, chat_id: int) -> int:
    row = (
        await db.execute(
            text(
                """
                SELECT COUNT(*) AS cnt
                FROM call_broadcast_jobs
                WHERE chat_id = :chat_id
                  AND trigger_source = 'inbound_call'
                  AND status = 'completed'
                """
            ),
            {"chat_id": int(chat_id)},
        )
    ).first()
    return int(_row_mapping(row).get("cnt") or 0)


async def resolve_video_asset_by_play_sequence(
    db: AsyncSession,
    play_sequence: int,
) -> dict[str, Any] | None:
    row = (
        await db.execute(
            text(
                """
                SELECT id, title, file_path, duration_seconds, ffmpeg_profile, play_sequence
                FROM video_broadcast_assets
                WHERE status = 'active' AND play_sequence = :play_sequence
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"play_sequence": int(play_sequence)},
        )
    ).first()
    return _row_mapping(row) if row is not None else None


async def resolve_inbound_sequence_video_asset(
    db: AsyncSession,
    chat_id: int,
) -> dict[str, Any] | None:
    """Pick video for the next inbound call: 1st→seq1, 2nd→seq2, 3rd→seq3."""
    completed = await count_completed_inbound_calls_for_chat(db, chat_id)
    inbound_call_number = completed + 1
    if inbound_call_number > INBOUND_PLAY_SEQUENCE_MAX:
        return None
    target_sequence = inbound_call_number

    for seq in range(target_sequence, 0, -1):
        asset = await resolve_video_asset_by_play_sequence(db, seq)
        if asset is not None:
            asset["inbound_call_number"] = inbound_call_number
            asset["requested_play_sequence"] = target_sequence
            asset["resolved_play_sequence"] = seq
            return asset

    fallback = await resolve_default_video_asset(db)
    if fallback is not None:
        fallback["inbound_call_number"] = inbound_call_number
        fallback["requested_play_sequence"] = target_sequence
        fallback["resolved_play_sequence"] = fallback.get("play_sequence")
    return fallback


async def enqueue_call_broadcast_job(
    db: AsyncSession,
    *,
    user_id: str,
    external_user_id: str | None,
    conversation_id: str | None,
    chat_id: int,
    account_id: str | None,
    trigger_source: str,
    matched_keyword: str | None,
    trace_id: str | None,
    video_asset_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    if (
        matched_keyword in TEST_IMMEDIATE_VIDEO_CALL_CODES
        or trigger_source in ("admin_manual", "inbound_call")
    ):
        # Test codes and operator-initiated calls may be repeated; skip 24h dedup.
        rule_key = (
            f"call:{trigger_source}:{conversation_id or user_id}:"
            f"{video_asset_id or 'default'}:{int(time.time() * 1000)}"
        )
    else:
        rule_key = f"call:{trigger_source}:{conversation_id or user_id}:{matched_keyword or 'generic'}"
    payload = {
        "matched_keyword": matched_keyword,
        **(metadata or {}),
    }
    result = await db.execute(
        text(
            """
            INSERT INTO call_broadcast_jobs (
                user_id, external_user_id, conversation_id, chat_id, account_id,
                video_asset_id, trigger_source, status, send_at, rule_key,
                metadata, trace_id
            )
            SELECT
                :user_id, :external_user_id, :conversation_id, :chat_id,
                NULLIF(:account_id, '')::uuid, NULLIF(:video_asset_id, '')::uuid,
                :trigger_source, 'pending', NOW(), :rule_key,
                CAST(:metadata AS jsonb), :trace_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM call_broadcast_jobs
                WHERE rule_key = :rule_key
                  AND status IN ('pending', 'dialing', 'streaming', 'completed')
                  AND created_at >= NOW() - INTERVAL '24 hours'
            )
            RETURNING id
            """
        ),
        {
            "user_id": user_id,
            "external_user_id": external_user_id,
            "conversation_id": conversation_id,
            "chat_id": chat_id,
            "account_id": account_id,
            "video_asset_id": video_asset_id,
            "trigger_source": trigger_source,
            "rule_key": rule_key,
            "metadata": json.dumps(payload, ensure_ascii=False),
            "trace_id": trace_id,
        },
    )
    return 1 if result.first() is not None else 0


async def claim_next_call_broadcast_job(
    db: AsyncSession,
    *,
    account_id: str | None = None,
) -> dict[str, Any] | None:
    account_clause = ""
    params: dict[str, Any] = {}
    if account_id:
        account_clause = """
                      AND (
                          j.account_id IS NULL
                          OR j.account_id::text = :account_id
                      )
        """
        params["account_id"] = account_id

    row = (
        await db.execute(
            text(
                f"""
                WITH picked AS (
                    SELECT j.id
                    FROM call_broadcast_jobs j
                    WHERE j.status = 'pending'
                      AND j.send_at <= NOW()
                      AND j.retry_count < j.max_retries
                      {account_clause}
                      AND NOT EXISTS (
                          SELECT 1
                          FROM call_broadcast_jobs busy
                          WHERE busy.account_id = j.account_id
                            AND busy.status IN ('dialing', 'streaming')
                            AND busy.id <> j.id
                      )
                    ORDER BY j.priority DESC, j.send_at ASC, j.created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE call_broadcast_jobs j
                SET status = 'dialing',
                    started_at = NOW(),
                    updated_at = NOW()
                FROM picked
                WHERE j.id = picked.id
                RETURNING j.id, j.user_id, j.external_user_id, j.conversation_id, j.chat_id,
                          j.account_id, j.video_asset_id, j.trigger_source, j.metadata,
                          j.trace_id, j.retry_count, j.max_retries
                """
            ),
            params,
        )
    ).first()
    return _row_mapping(row) if row is not None else None


async def mark_job_streaming(db: AsyncSession, job_id: str) -> None:
    await db.execute(
        text(
            """
            UPDATE call_broadcast_jobs
            SET status = 'streaming', updated_at = NOW()
            WHERE id = CAST(:job_id AS uuid)
            """
        ),
        {"job_id": job_id},
    )


async def requeue_job(
    db: AsyncSession,
    *,
    job_id: str,
    failure_reason: str | None = None,
) -> None:
    await db.execute(
        text(
            """
            UPDATE call_broadcast_jobs
            SET status = 'pending',
                started_at = NULL,
                updated_at = NOW(),
                failure_reason = :failure_reason
            WHERE id = CAST(:job_id AS uuid)
            """
        ),
        {"job_id": job_id, "failure_reason": failure_reason},
    )


async def finalize_job(
    db: AsyncSession,
    *,
    job_id: str,
    status: str,
    failure_reason: str | None = None,
    increment_retry: bool = False,
) -> None:
    await db.execute(
        text(
            """
            UPDATE call_broadcast_jobs
            SET status = :status,
                ended_at = CASE
                    WHEN :status IN ('completed', 'failed', 'cancelled') THEN NOW()
                    ELSE ended_at
                END,
                started_at = CASE
                    WHEN :increment_retry THEN NULL
                    ELSE started_at
                END,
                updated_at = NOW(),
                failure_reason = :failure_reason,
                retry_count = CASE
                    WHEN :increment_retry THEN retry_count + 1
                    ELSE retry_count
                END,
                send_at = CASE
                    WHEN :increment_retry THEN NOW() + INTERVAL '2 minutes'
                    ELSE send_at
                END
            WHERE id = CAST(:job_id AS uuid)
            """
        ),
        {
            "job_id": job_id,
            "status": status,
            "failure_reason": failure_reason,
            "increment_retry": increment_retry,
        },
    )


async def load_video_asset_for_job(
    db: AsyncSession,
    *,
    video_asset_id: str | None,
) -> dict[str, Any] | None:
    if video_asset_id:
        row = (
            await db.execute(
                text(
                    """
                    SELECT id, title, file_path, duration_seconds, ffmpeg_profile
                    FROM video_broadcast_assets
                    WHERE id = CAST(:asset_id AS uuid) AND status = 'active'
                    LIMIT 1
                    """
                ),
                {"asset_id": video_asset_id},
            )
        ).first()
        if row is not None:
            return _row_mapping(row)
    return await resolve_default_video_asset(db)


async def create_inbound_operator_review_job(
    db: AsyncSession,
    *,
    chat_id: int,
    account_id: str,
    trace_id: str,
    telegram_access_hash: int | None = None,
    inbound_call_number: int,
) -> str | None:
    user_id = f"tg_{chat_id}"
    rule_key = f"call:inbound_operator_review:{chat_id}:{account_id}:{int(time.time() * 1000)}"
    metadata: dict[str, Any] = {
        "source": "incoming_operator_review",
        "inbound_call_number": inbound_call_number,
    }
    if telegram_access_hash is not None:
        metadata["telegram_access_hash"] = str(int(telegram_access_hash))
    row = (
        await db.execute(
            text(
                """
                INSERT INTO call_broadcast_jobs (
                    user_id, external_user_id, chat_id, account_id,
                    trigger_source, status, send_at, rule_key, metadata, trace_id
                )
                VALUES (
                    :user_id, :external_user_id, :chat_id, CAST(:account_id AS uuid),
                    'inbound_operator_review', 'pending_operator', NOW(), :rule_key,
                    CAST(:metadata AS jsonb), :trace_id
                )
                RETURNING id::text
                """
            ),
            {
                "user_id": user_id,
                "external_user_id": user_id,
                "chat_id": chat_id,
                "account_id": account_id,
                "rule_key": rule_key,
                "metadata": json.dumps(metadata, ensure_ascii=False),
                "trace_id": trace_id,
            },
        )
    ).first()
    if row is None:
        return None
    mapping = _row_mapping(row)
    return str(mapping.get("id") or row[0])


async def create_keyword_live_video_review_job(
    db: AsyncSession,
    *,
    user_id: str,
    external_user_id: str | None,
    conversation_id: str | None,
    chat_id: int,
    account_id: str,
    trace_id: str,
    matched_keyword: str,
    telegram_access_hash: int | None = None,
) -> str | None:
    """Queue a pending_operator job when user texts a live video-call request."""
    ext = external_user_id or f"tg_{chat_id}"
    rule_key = (
        f"call:keyword_live_video:{chat_id}:{account_id}:"
        f"{matched_keyword}:{int(time.time() * 1000)}"
    )
    metadata: dict[str, Any] = {
        "source": "keyword_live_video_call",
        "matched_keyword": matched_keyword,
        "inbound_call_number": 2,
        "conversation_id": conversation_id,
    }
    if telegram_access_hash is not None:
        metadata["telegram_access_hash"] = str(int(telegram_access_hash))
    row = (
        await db.execute(
            text(
                """
                INSERT INTO call_broadcast_jobs (
                    user_id, external_user_id, conversation_id, chat_id, account_id,
                    trigger_source, status, send_at, rule_key, metadata, trace_id
                )
                VALUES (
                    :user_id, :external_user_id, :conversation_id, :chat_id,
                    CAST(:account_id AS uuid), 'inbound_keyword_review', 'pending_operator',
                    NOW(), :rule_key, CAST(:metadata AS jsonb), :trace_id
                )
                RETURNING id::text
                """
            ),
            {
                "user_id": user_id,
                "external_user_id": ext,
                "conversation_id": conversation_id,
                "chat_id": chat_id,
                "account_id": account_id,
                "rule_key": rule_key,
                "metadata": json.dumps(metadata, ensure_ascii=False),
                "trace_id": trace_id,
            },
        )
    ).first()
    if row is None:
        return None
    mapping = _row_mapping(row)
    return str(mapping.get("id") or row[0])


async def create_inbound_auto_answer_job(
    db: AsyncSession,
    *,
    chat_id: int,
    account_id: str,
    video_asset_id: str | None,
    trace_id: str,
    telegram_access_hash: int | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> str | None:
    """Insert an inbound auto-answer job already in dialing state (audit trail)."""
    user_id = f"tg_{chat_id}"
    rule_key = f"call:inbound_call:{chat_id}:{account_id}:{int(time.time() * 1000)}"
    metadata: dict[str, Any] = {"source": "incoming_auto_answer", **(extra_metadata or {})}
    if telegram_access_hash is not None:
        metadata["telegram_access_hash"] = str(int(telegram_access_hash))
    row = (
        await db.execute(
            text(
                """
                INSERT INTO call_broadcast_jobs (
                    user_id, external_user_id, chat_id, account_id, video_asset_id,
                    trigger_source, status, send_at, started_at, rule_key, metadata, trace_id
                )
                VALUES (
                    :user_id, :external_user_id, :chat_id, CAST(:account_id AS uuid),
                    NULLIF(:video_asset_id, '')::uuid, 'inbound_call', 'dialing', NOW(), NOW(),
                    :rule_key, CAST(:metadata AS jsonb), :trace_id
                )
                RETURNING id::text
                """
            ),
            {
                "user_id": user_id,
                "external_user_id": user_id,
                "chat_id": chat_id,
                "account_id": account_id,
                "video_asset_id": video_asset_id or "",
                "rule_key": rule_key,
                "metadata": json.dumps(metadata, ensure_ascii=False),
                "trace_id": trace_id,
            },
        )
    ).first()
    if row is None:
        return None
    mapping = _row_mapping(row)
    return str(mapping.get("id") or row[0])


async def count_active_calls_for_account(db: AsyncSession, account_id: UUID) -> int:
    row = (
        await db.execute(
            text(
                """
                SELECT COUNT(*) AS cnt
                FROM call_broadcast_jobs
                WHERE account_id = CAST(:account_id AS uuid)
                  AND status IN ('dialing', 'streaming')
                """
            ),
            {"account_id": str(account_id)},
        )
    ).first()
    mapping = _row_mapping(row)
    return int(mapping.get("cnt") or 0)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
