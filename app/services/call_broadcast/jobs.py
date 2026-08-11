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
from services.call_broadcast.duration import CallPlaybackResult
from services.call_broadcast.keywords import TEST_IMMEDIATE_VIDEO_CALL_CODES
from services.call_broadcast.session import resolve_stale_active_slack_seconds


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


async def record_inbound_call_event(
    db: AsyncSession,
    *,
    account_id: str,
    chat_id: int,
    event_key: str,
    trace_id: str | None = None,
) -> bool:
    """Persist one Telegram-originated inbound ring; duplicates do not increment."""
    row = (await db.execute(
        text("""INSERT INTO telegram_inbound_call_events
                (account_id, chat_id, event_key, trace_id)
                VALUES (CAST(:account_id AS uuid), :chat_id, :event_key, :trace_id)
                ON CONFLICT (account_id, event_key) DO NOTHING
                RETURNING id"""),
        {
            "account_id": account_id,
            "chat_id": int(chat_id),
            "event_key": event_key,
            "trace_id": trace_id,
        },
    )).first()
    return row is not None


async def count_inbound_call_events_for_chat(db: AsyncSession, chat_id: int) -> int:
    row = (await db.execute(
        text("SELECT COUNT(*) FROM telegram_inbound_call_events WHERE chat_id = :chat_id"),
        {"chat_id": int(chat_id)},
    )).first()
    return int(row[0] if row else 0)


async def count_completed_inbound_auto_answer_calls_for_chat(
    db: AsyncSession,
    chat_id: int,
    *,
    account_id: str | None = None,
    since: Any | None = None,
) -> int:
    """Completed inbound auto-answer playbacks (play_sequence 1/2 path)."""
    row = (
        await db.execute(
            text(
                """
                SELECT COUNT(*) AS cnt
                FROM call_broadcast_jobs
                WHERE chat_id = :chat_id
                  AND trigger_source = 'inbound_call'
                  AND status = 'completed'
                  AND COALESCE(metadata->>'source', '') = 'incoming_auto_answer'
                  AND (CAST(:account_id AS uuid) IS NULL OR account_id = CAST(:account_id AS uuid))
                  AND (CAST(:since AS timestamptz) IS NULL OR created_at >= CAST(:since AS timestamptz))
                """
            ),
            {"chat_id": int(chat_id), "account_id": account_id, "since": since},
        )
    ).first()
    return int(_row_mapping(row).get("cnt") or 0)


async def count_completed_inbound_calls_for_chat(
    db: AsyncSession,
    chat_id: int,
    *,
    account_id: str | None = None,
    since: Any | None = None,
) -> int:
    """Successful inbound playbacks (auto-answer + operator-handled)."""
    row = (
        await db.execute(
            text(
                """
                SELECT COUNT(*) AS cnt
                FROM call_broadcast_jobs
                WHERE chat_id = :chat_id
                  AND trigger_source IN ('inbound_call', 'inbound_operator_review')
                  AND status = 'completed'
                  AND (CAST(:account_id AS uuid) IS NULL OR account_id = CAST(:account_id AS uuid))
                  AND (CAST(:since AS timestamptz) IS NULL OR created_at >= CAST(:since AS timestamptz))
                """
            ),
            {"chat_id": int(chat_id), "account_id": account_id, "since": since},
        )
    ).first()
    return int(_row_mapping(row).get("cnt") or 0)


async def count_prior_inbound_call_attempts(
    db: AsyncSession,
    chat_id: int,
    *,
    account_id: str | None = None,
    since: Any | None = None,
) -> int:
    """Inbound rings already recorded for this chat (auto-answer + operator-review attempts)."""
    row = (
        await db.execute(
            text(
                """
                SELECT COUNT(*) AS cnt
                FROM call_broadcast_jobs
                WHERE chat_id = :chat_id
                  AND trigger_source IN ('inbound_call', 'inbound_operator_review')
                  AND (CAST(:account_id AS uuid) IS NULL OR account_id = CAST(:account_id AS uuid))
                  AND (CAST(:since AS timestamptz) IS NULL OR created_at >= CAST(:since AS timestamptz))
                """
            ),
            {"chat_id": int(chat_id), "account_id": account_id, "since": since},
        )
    ).first()
    return int(_row_mapping(row).get("cnt") or 0)


async def count_completed_call_broadcasts_for_chat(db: AsyncSession, chat_id: int) -> int:
    """All completed video broadcasts for this chat (any trigger source)."""
    row = (
        await db.execute(
            text(
                """
                SELECT COUNT(*) AS cnt
                FROM call_broadcast_jobs
                WHERE chat_id = :chat_id
                  AND status = 'completed'
                """
            ),
            {"chat_id": int(chat_id)},
        )
    ).first()
    return int(_row_mapping(row).get("cnt") or 0)


async def count_all_call_broadcasts_for_chat(db: AsyncSession, chat_id: int) -> int:
    """All video-call records for this chat, including failed/cancelled/operator jobs."""
    row = (
        await db.execute(
            text(
                """
                SELECT COUNT(*) AS cnt
                FROM call_broadcast_jobs
                WHERE chat_id = :chat_id
                """
            ),
            {"chat_id": int(chat_id)},
        )
    ).first()
    return int(_row_mapping(row).get("cnt") or 0)


async def resolve_inbound_call_context(
    db: AsyncSession,
    chat_id: int,
) -> dict[str, int]:
    """Inbound playback ordinal vs ring-attempt count vs overall call history."""
    completed_inbound = await count_completed_inbound_calls_for_chat(db, chat_id)
    recorded_attempts = await count_prior_inbound_call_attempts(db, chat_id)
    completed_calls = await count_completed_call_broadcasts_for_chat(db, chat_id)
    total_calls = await count_all_call_broadcasts_for_chat(db, chat_id)
    return {
        "completed_inbound_calls": completed_inbound,
        "prior_inbound_attempts": recorded_attempts,
        "recorded_attempts": recorded_attempts,
        # Next video sequence slot (1/2/3) after successful playbacks.
        "inbound_call_number": completed_inbound + 1,
        # How many times the user has already rung (including cancelled reviews).
        "call_attempt_number": recorded_attempts + 1,
        "completed_calls": completed_calls,
        "call_number": max(total_calls, recorded_attempts + 1),
    }


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
    *,
    completed_count: int | None = None,
) -> dict[str, Any] | None:
    """Pick video for the next inbound call: 1st→seq1, 2nd→seq2, 3rd→seq3."""
    completed = (
        int(completed_count)
        if completed_count is not None
        else await count_completed_inbound_calls_for_chat(db, chat_id)
    )
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
            SET status = 'streaming',
                started_at = COALESCE(started_at, NOW()),
                updated_at = NOW()
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
    playback_seconds: float | int | None = None,
    playback_result: CallPlaybackResult | None = None,
) -> None:
    metadata_sql = ""
    params: dict[str, Any] = {
        "job_id": job_id,
        "status": status,
        "failure_reason": failure_reason,
        "increment_retry": increment_retry,
    }
    metadata_patch: dict[str, Any] | None = None
    if playback_result is not None:
        metadata_patch = playback_result.metadata_patch()
    elif playback_seconds is not None:
        metadata_patch = CallPlaybackResult(
            playback_seconds=float(playback_seconds)
        ).metadata_patch()
    if metadata_patch:
        metadata_sql = (
            ", metadata = COALESCE(metadata, '{}'::jsonb) || CAST(:metadata_patch AS jsonb)"
        )
        params["metadata_patch"] = json.dumps(metadata_patch, ensure_ascii=False)
    await db.execute(
        text(
            f"""
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
                {metadata_sql}
            WHERE id = CAST(:job_id AS uuid)
            """
        ),
        params,
    )


async def finalize_stale_active_jobs(db: AsyncSession) -> int:
    """Fail active call jobs that survived past their expected playback window."""
    default_duration = int(getattr(settings, "CALL_BROADCAST_DEFAULT_DURATION_SECONDS", 30))
    stale_slack_seconds = resolve_stale_active_slack_seconds()
    min_seconds = int(getattr(settings, "CALL_BROADCAST_STALE_ACTIVE_MIN_SECONDS", 300))
    row = (
        await db.execute(
            text(
                """
                WITH stale AS (
                    SELECT j.id
                    FROM call_broadcast_jobs j
                    LEFT JOIN video_broadcast_assets v ON v.id = j.video_asset_id
                    WHERE j.status IN ('dialing', 'running', 'streaming')
                      AND EXTRACT(EPOCH FROM (NOW() - COALESCE(j.started_at, j.updated_at, j.created_at))) >
                          GREATEST(
                              COALESCE(v.duration_seconds, :default_duration)::int + :stale_slack_seconds,
                              :min_seconds
                          )
                ),
                updated AS (
                    UPDATE call_broadcast_jobs j
                    SET status = 'failed',
                        ended_at = NOW(),
                        updated_at = NOW(),
                        failure_reason = 'stale_active_call_timeout'
                    FROM stale
                    WHERE j.id = stale.id
                    RETURNING j.id
                )
                SELECT COUNT(*) AS cnt FROM updated
                """
            ),
            {
                "default_duration": default_duration,
                "stale_slack_seconds": stale_slack_seconds,
                "min_seconds": min_seconds,
            },
        )
    ).first()
    return int(_row_mapping(row).get("cnt") or 0)


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
    call_attempt_number: int | None = None,
) -> str | None:
    user_id = f"tg_{chat_id}"
    rule_key = f"call:inbound_operator_review:{chat_id}:{account_id}:{int(time.time() * 1000)}"
    metadata: dict[str, Any] = {
        "source": "incoming_operator_review",
        "inbound_call_number": inbound_call_number,
    }
    if call_attempt_number is not None:
        metadata["call_attempt_number"] = call_attempt_number
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
    inbound_call_number: int | None = None,
    completed_inbound_calls: int | None = None,
) -> str | None:
    """Queue a pending_operator job when user texts a live video-call request."""
    ext = external_user_id or f"tg_{chat_id}"
    call_ctx = await resolve_inbound_call_context(db, chat_id)
    call_number = int(inbound_call_number or call_ctx["call_number"])
    completed_calls = int(call_ctx["completed_calls"])
    completed_inbound = int(
        completed_inbound_calls if completed_inbound_calls is not None else call_ctx["completed_inbound_calls"]
    )
    inbound_call_number = int(call_ctx["inbound_call_number"])
    rule_key = (
        f"call:keyword_live_video:{chat_id}:{account_id}:"
        f"{matched_keyword}:{int(time.time() * 1000)}"
    )
    metadata: dict[str, Any] = {
        "source": "keyword_live_video_call",
        "matched_keyword": matched_keyword,
        "call_number": call_number,
        "completed_calls": completed_calls,
        "inbound_call_number": inbound_call_number,
        "completed_inbound_calls": completed_inbound,
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
