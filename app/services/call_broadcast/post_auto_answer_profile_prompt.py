"""Ask for city and age after the second auto-answer video when missing."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.mtproto.peer_resolve import resolve_telethon_peer
from services.profile_intake import age_from_preferences, normalize_country_code
from services.telegram_account_manager import telegram_account_manager
from services.outbound_account_gate import check_outbound_account, pause_outbound_account

_CITY_KEYS = ("current_city", "city", "user_city", "location")


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _has_city(preferences: dict[str, Any]) -> bool:
    return any(str(preferences.get(key) or "").strip() for key in _CITY_KEYS)


def _build_prompt(missing: list[str]) -> str:
    question_by_field = {
        "city": "which city are you from",
        "age": "how old are you",
    }
    questions = [question_by_field[field] for field in missing if field in question_by_field]
    if not questions:
        return ""
    if len(questions) == 1:
        return f"By the way, {questions[0]}?"
    return f"By the way, {', and '.join(questions)}?"


async def _load_profile_state(db: AsyncSession, *, external_user_id: str) -> dict[str, Any]:
    row = (
        await db.execute(
            text(
                """
                SELECT u.id::text AS user_uuid, p.country_code, p.preferences
                FROM users u
                LEFT JOIN user_profiles p ON p.user_id = u.id
                WHERE u.external_id = :external_user_id
                LIMIT 1
                """
            ),
            {"external_user_id": external_user_id},
        )
    ).fetchone()
    if not row:
        return {"user_uuid": None, "country_code": None, "preferences": {}}
    data = row._mapping if hasattr(row, "_mapping") else row
    preferences = _as_dict(data["preferences"])
    return {
        "user_uuid": data["user_uuid"],
        "country_code": normalize_country_code(data["country_code"])
        or normalize_country_code(preferences.get("country_code") or preferences.get("country")),
        "preferences": preferences,
    }


async def _latest_conversation_id(db: AsyncSession, *, user_uuid: str | None) -> str | None:
    if not user_uuid:
        return None
    row = (
        await db.execute(
            text(
                """
                SELECT id::text
                FROM conversations
                WHERE user_id = CAST(:uid AS uuid)
                ORDER BY COALESCE(last_message_at, updated_at, created_at) DESC
                LIMIT 1
                """
            ),
            {"uid": user_uuid},
        )
    ).fetchone()
    return str(row[0]) if row and row[0] else None


async def maybe_send_second_auto_answer_profile_prompt(
    db: AsyncSession,
    *,
    job_id: str,
    account_id: str,
    chat_id: int,
    telegram_access_hash: int | None,
    completed_auto_answer_count: int,
    trace_id: str | None,
    external_user_id: str | None = None,
    conversation_id: str | None = None,
) -> bool:
    """Send one city/age prompt after two or more auto answers when missing."""
    log = logger.bind(
        component="call_broadcast_post_auto_answer_profile_prompt",
        trace_id=trace_id,
        job_id=job_id,
        chat_id=chat_id,
    )
    if completed_auto_answer_count < 2:
        return False

    marker_row = (
        await db.execute(
            text(
                """
                SELECT 1
                FROM call_broadcast_jobs
                WHERE chat_id = :chat_id
                  AND trigger_source = 'inbound_call'
                  AND status = 'completed'
                  AND COALESCE(metadata->>'source', '') = 'incoming_auto_answer'
                  AND COALESCE(metadata->>'post_auto_profile_prompt_sent', '') = 'true'
                LIMIT 1
                """
            ),
            {"chat_id": int(chat_id)},
        )
    ).fetchone()
    if marker_row:
        return False

    profile = await _load_profile_state(
        db,
        external_user_id=external_user_id or f"tg_{int(chat_id)}",
    )
    preferences = profile["preferences"]
    missing: list[str] = []
    if not _has_city(preferences):
        missing.append("city")
    if age_from_preferences(preferences) is None:
        missing.append("age")
    if not missing:
        log.info("post_auto_profile_prompt.skip_city_age_known")
        await db.execute(text("""UPDATE call_broadcast_jobs SET metadata=COALESCE(metadata,'{}'::jsonb)
          || '{"post_auto_profile_prompt_skipped":true}'::jsonb,updated_at=NOW()
          WHERE id=CAST(:job_id AS uuid)"""), {"job_id": job_id})
        return False

    allowed, gate_reason, resume_at = await check_outbound_account(db, account_id)
    if not allowed:
        await _record_prompt_retry(db, job_id, gate_reason, resume_at or datetime.now(timezone.utc)+timedelta(hours=24))
        return False

    content = _build_prompt(missing)
    client = await telegram_account_manager.get_client(UUID(str(account_id)))
    if client is None:
        log.warning("post_auto_profile_prompt.skip_no_client")
        return False
    peer = await resolve_telethon_peer(client, int(chat_id), access_hash=telegram_access_hash)
    sent = await client.send_message(peer, content)

    resolved_conversation_id = conversation_id or await _latest_conversation_id(
        db,
        user_uuid=profile["user_uuid"],
    )
    if resolved_conversation_id:
        await db.execute(
            text(
                """
                INSERT INTO messages (
                    id, conversation_id, sender_type, sender_id, content,
                    content_type, model_name, created_at
                )
                VALUES (
                    :id, CAST(:conversation_id AS uuid), 'assistant', :sender_id,
                    :content, 'text', 'post_auto_answer_profile_prompt', NOW()
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "conversation_id": resolved_conversation_id,
                "sender_id": str(account_id),
                "content": content,
            },
        )
        await db.execute(
            text("UPDATE conversations SET last_message_at=NOW(), updated_at=NOW() WHERE id=CAST(:id AS uuid)"),
            {"id": resolved_conversation_id},
        )
    else:
        log.warning("post_auto_profile_prompt.sent_without_conversation")

    await db.execute(
        text(
            """
            UPDATE call_broadcast_jobs
            SET metadata = COALESCE(metadata, '{}'::jsonb) || CAST(:patch AS jsonb),
                updated_at = NOW()
            WHERE id = CAST(:job_id AS uuid)
            """
        ),
        {
            "job_id": job_id,
            "patch": json.dumps(
                {
                    "post_auto_profile_prompt_sent": True,
                    "post_auto_profile_prompt_message_id": str(getattr(sent, "id", "") or ""),
                    "post_auto_profile_prompt_missing": missing,
                    "post_auto_profile_prompt_saved": bool(resolved_conversation_id),
                },
                ensure_ascii=False,
            ),
        },
    )
    log.bind(missing=missing).info("post_auto_profile_prompt.sent")
    return True


async def run_pending_second_auto_answer_profile_prompts(
    db: AsyncSession,
    *,
    limit: int = 5,
    trace_id: str | None = None,
) -> dict[str, int]:
    """Compensate users who already passed two auto answers but missed the prompt."""
    log = logger.bind(
        component="call_broadcast_post_auto_answer_profile_prompt",
        trace_id=trace_id,
    )
    rows = (
        await db.execute(
            text(
                """
                WITH completed AS (
                    SELECT chat_id, external_user_id, COUNT(*) AS completed_count
                    FROM call_broadcast_jobs
                    WHERE trigger_source = 'inbound_call'
                      AND status = 'completed'
                      AND COALESCE(metadata->>'source', '') = 'incoming_auto_answer'
                    GROUP BY chat_id, external_user_id
                    HAVING COUNT(*) >= 2
                ),
                latest_job AS (
                    SELECT DISTINCT ON (j.chat_id)
                        j.id::text AS job_id,
                        COALESCE(tpc.account_id::text, j.account_id::text) AS account_id,
                        j.chat_id,
                        j.external_user_id,
                        COALESCE(NULLIF(j.conversation_id, ''), tpc.conversation_id::text) AS conversation_id,
                        CASE
                            WHEN tpc.access_hash IS NOT NULL THEN
                                COALESCE(j.metadata, '{}'::jsonb) || jsonb_build_object('telegram_access_hash', tpc.access_hash::text)
                            ELSE COALESCE(j.metadata, '{}'::jsonb)
                        END AS metadata,
                        j.created_at,
                        c.completed_count
                    FROM call_broadcast_jobs j
                    JOIN completed c ON c.chat_id = j.chat_id
                    LEFT JOIN LATERAL (
                        SELECT account_id, conversation_id, access_hash
                        FROM telegram_peer_cache
                        WHERE chat_id = j.chat_id
                        ORDER BY COALESCE(updated_at, created_at) DESC
                        LIMIT 1
                    ) tpc ON TRUE
                    WHERE j.trigger_source = 'inbound_call'
                      AND j.status = 'completed'
                      AND COALESCE(j.metadata->>'source', '') = 'incoming_auto_answer'
                    ORDER BY j.chat_id, j.created_at DESC
                ),
                marked AS (
                    SELECT DISTINCT chat_id
                    FROM call_broadcast_jobs
                    WHERE trigger_source = 'inbound_call'
                      AND status = 'completed'
                      AND COALESCE(metadata->>'source', '') = 'incoming_auto_answer'
                      AND (COALESCE(metadata->>'post_auto_profile_prompt_sent', '') = 'true'
                           OR COALESCE(metadata->>'post_auto_profile_prompt_skipped', '') = 'true')
                )
                SELECT
                    latest_job.job_id,
                    latest_job.account_id,
                    latest_job.chat_id,
                    latest_job.external_user_id,
                    latest_job.conversation_id,
                    latest_job.metadata,
                    latest_job.completed_count
                FROM latest_job
                LEFT JOIN marked ON marked.chat_id = latest_job.chat_id
                WHERE marked.chat_id IS NULL
                  AND COALESCE((latest_job.metadata->>'post_auto_profile_prompt_attempts')::int,0)<3
                  AND (NULLIF(latest_job.metadata->>'post_auto_profile_prompt_next_attempt_at','') IS NULL
                       OR (latest_job.metadata->>'post_auto_profile_prompt_next_attempt_at')::timestamptz<=NOW())
                ORDER BY latest_job.created_at ASC
                LIMIT :limit
                """
            ),
            {"limit": max(1, min(int(limit), 20))},
        )
    ).fetchall()
    stats = {"candidates": len(rows), "sent": 0, "skipped": 0, "failed": 0}
    for row in rows:
        data = row._mapping if hasattr(row, "_mapping") else row
        metadata = _as_dict(data["metadata"])
        raw_access_hash = metadata.get("telegram_access_hash")
        try:
            telegram_access_hash = int(str(raw_access_hash)) if raw_access_hash else None
            sent = await maybe_send_second_auto_answer_profile_prompt(
                db,
                job_id=str(data["job_id"]),
                account_id=str(data["account_id"]),
                chat_id=int(data["chat_id"]),
                telegram_access_hash=telegram_access_hash,
                completed_auto_answer_count=int(data["completed_count"] or 0),
                trace_id=trace_id,
                external_user_id=str(data["external_user_id"] or f"tg_{int(data['chat_id'])}"),
                conversation_id=str(data["conversation_id"] or "") or None,
            )
            if sent:
                stats["sent"] += 1
            else:
                stats["skipped"] += 1
        except Exception as exc:
            stats["failed"] += 1
            reason = f"{type(exc).__name__}: {str(exc)[:180]}"
            if "peerflood" in reason.lower() and data["account_id"]:
                await pause_outbound_account(db, str(data["account_id"]), reason=reason, hours=24)
                next_at = datetime.now(timezone.utc) + timedelta(hours=24)
            else:
                next_at = datetime.now(timezone.utc) + timedelta(minutes=30)
            await _record_prompt_retry(db, str(data["job_id"]), reason, next_at)
            await db.commit()
            log.bind(
                chat_id=data["chat_id"],
                error_type=type(exc).__name__,
            ).warning("post_auto_profile_prompt.compensation_failed")
    if rows:
        log.bind(**stats).info("post_auto_profile_prompt.compensation_tick")
    return stats


async def _record_prompt_retry(db: AsyncSession, job_id: str, reason: str, next_at: datetime) -> None:
    await db.execute(text("""
      UPDATE call_broadcast_jobs SET metadata=COALESCE(metadata,'{}'::jsonb) || jsonb_build_object(
        'post_auto_profile_prompt_attempts',COALESCE((metadata->>'post_auto_profile_prompt_attempts')::int,0)+1,
        'post_auto_profile_prompt_last_error',CAST(:reason AS text),
        'post_auto_profile_prompt_next_attempt_at',CAST(:next_at AS text)),updated_at=NOW()
      WHERE id=CAST(:job_id AS uuid)
    """), {"job_id": job_id, "reason": reason[:500], "next_at": next_at.isoformat()})
