"""Human takeover gate: block AI while operator owns the thread, release after idle timeout."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from services.user_reply_guard import BLOCKED_CONVERSATION_STATES

HUMAN_CONTROL_STATES = frozenset({"HUMAN_LOCKED", "WAITING_OPERATOR"})
DELIVERY_MODE = "human_takeover_ai_resume"
MESSAGE_TYPE = "human_takeover_ai_resume"


@dataclass(frozen=True)
class HumanTakeoverGateResult:
    allows_auto_reply: bool
    released_to_ai: bool
    reason: str


def _as_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return None


def _idle_deadline_passed(
    *,
    now: datetime,
    takeover_at: datetime | None,
    last_user_at: datetime | None,
    last_operator_at: datetime | None,
    idle_seconds: int,
) -> bool:
    if last_operator_at is not None:
        return False

    if takeover_at and (not last_operator_at or last_operator_at < takeover_at):
        if (now - takeover_at).total_seconds() >= idle_seconds:
            return True

    if last_user_at and (not last_operator_at or last_operator_at < last_user_at):
        reference = last_user_at
        if takeover_at and takeover_at > reference:
            reference = takeover_at
        if (now - reference).total_seconds() >= idle_seconds:
            return True

    return False


async def _fetch_gate_row(db: AsyncSession, conversation_id: str) -> dict[str, Any] | None:
    row = (
        await db.execute(
            text(
                """
                SELECT
                  c.state,
                  c.user_id::text AS user_id,
                  EXISTS (
                    SELECT 1
                    FROM handoff_tasks t1ht
                    WHERE t1ht.conversation_id = c.id
                      AND t1ht.closed_at IS NULL
                      AND t1ht.trigger_reason = 't1_country_manual_chat'
                  ) AS is_t1_manual_handoff,
                  COALESCE(
                    (
                      SELECT MAX(ht.locked_at)
                      FROM handoff_tasks ht
                      WHERE ht.conversation_id = c.id
                        AND ht.locked_at IS NOT NULL
                    ),
                    c.updated_at
                  ) AS human_takeover_at,
                  (
                    SELECT MAX(m.created_at)
                    FROM messages m
                    WHERE m.conversation_id = c.id
                      AND m.sender_type = 'user'
                  ) AS last_user_at,
                  (
                    SELECT MAX(m.created_at)
                    FROM messages m
                    WHERE m.conversation_id = c.id
                      AND (
                        m.sender_type = 'operator'
                        OR COALESCE(m.is_operator_message, false) = true
                      )
                  ) AS last_operator_at
                FROM conversations c
                WHERE c.id = CAST(:cid AS uuid)
                """
            ),
            {"cid": conversation_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def ensure_t1_manual_handoff(
    db: AsyncSession,
    *,
    conversation_id: str,
    user_id: str,
) -> None:
    from services.fixed_followup_ai import enabled as bounded_ai_enabled
    if await bounded_ai_enabled(db):
        return
    await db.execute(
        text(
            """
            UPDATE conversations
            SET state=CASE WHEN state='HUMAN_LOCKED' THEN state ELSE 'WAITING_OPERATOR' END,
                assigned_operator_id=CASE
                  WHEN state='HUMAN_LOCKED' THEN assigned_operator_id ELSE NULL END,
                handoff_count=COALESCE(handoff_count,0)+
                  CASE WHEN state IN ('WAITING_OPERATOR','HUMAN_LOCKED') THEN 0 ELSE 1 END,
                updated_at=NOW()
            WHERE id=CAST(:cid AS uuid)
              AND state NOT IN ('FROZEN','CLOSED')
            """
        ),
        {"cid": conversation_id},
    )
    await db.execute(
        text(
            """
            INSERT INTO handoff_tasks
              (id,user_id,conversation_id,priority,trigger_reason,status,created_at)
            SELECT gen_random_uuid(),CAST(:uid AS uuid),CAST(:cid AS uuid),
                   'high','t1_country_manual_chat','pending',NOW()
            WHERE NOT EXISTS (
              SELECT 1 FROM handoff_tasks
              WHERE conversation_id=CAST(:cid AS uuid)
                AND closed_at IS NULL
                AND status IN ('pending','PENDING','WAITING_OPERATOR','HUMAN_LOCKED')
            )
            """
        ),
        {"uid": user_id, "cid": conversation_id},
    )


async def release_human_takeover_to_ai(
    db: AsyncSession,
    conversation_id: str,
    *,
    reason: str,
) -> bool:
    updated = (
        await db.execute(
            text(
                """
                UPDATE conversations
                SET state = 'AI_ACTIVE',
                    updated_at = NOW()
                WHERE id = CAST(:cid AS uuid)
                  AND state IN ('HUMAN_LOCKED', 'WAITING_OPERATOR')
                RETURNING id
                """
            ),
            {"cid": conversation_id},
        )
    ).fetchone()
    if not updated:
        return False

    await db.execute(
        text(
            """
            UPDATE handoff_tasks
            SET status = 'CLOSED',
                closed_at = COALESCE(closed_at, NOW())
            WHERE conversation_id = CAST(:cid AS uuid)
              AND status IN ('pending', 'PENDING', 'HUMAN_LOCKED', 'WAITING_OPERATOR')
            """
        ),
        {"cid": conversation_id},
    )
    logger.bind(conversation_id=conversation_id, reason=reason).info(
        "human_takeover_gate.released_to_ai"
    )
    return True


async def evaluate_human_takeover_gate(
    db: AsyncSession,
    conversation_id: str,
    *,
    now: datetime | None = None,
    idle_seconds: int | None = None,
) -> HumanTakeoverGateResult:
    """Return whether auto-reply may proceed; release to AI when idle timeout is reached."""
    from services.post_inbound_video_expert_gate import (
        conversation_requires_post_inbound_video_expert,
    )

    row = await _fetch_gate_row(db, conversation_id)
    if not row:
        return HumanTakeoverGateResult(
            allows_auto_reply=False,
            released_to_ai=False,
            reason="conversation_missing",
        )

    state = str(row.get("state") or "")
    if state in BLOCKED_CONVERSATION_STATES:
        return HumanTakeoverGateResult(
            allows_auto_reply=False,
            released_to_ai=False,
            reason=f"blocked_state:{state}",
        )

    if state not in HUMAN_CONTROL_STATES:
        if await conversation_requires_post_inbound_video_expert(
            db, conversation_id=conversation_id
        ):
            return HumanTakeoverGateResult(
                allows_auto_reply=False,
                released_to_ai=False,
                reason="post_inbound_video_expert_only",
            )
        return HumanTakeoverGateResult(
            allows_auto_reply=True,
            released_to_ai=False,
            reason="ai_active",
        )

    last_operator_at = _as_utc(row.get("last_operator_at"))
    if last_operator_at is not None:
        return HumanTakeoverGateResult(
            allows_auto_reply=False,
            released_to_ai=False,
            reason="human_operator_replied",
        )

    if bool(row.get("is_t1_manual_handoff")):
        from services.fixed_followup_ai import enabled as bounded_ai_enabled
        if not await bounded_ai_enabled(db):
            return HumanTakeoverGateResult(
                allows_auto_reply=False,
                released_to_ai=False,
                reason="t1_country_manual_chat",
            )

    if await conversation_requires_post_inbound_video_expert(db, conversation_id=conversation_id):
        return HumanTakeoverGateResult(
            allows_auto_reply=False,
            released_to_ai=False,
            reason="post_inbound_video_expert_only",
        )

    now_utc = now or datetime.now(timezone.utc)
    idle = idle_seconds if idle_seconds is not None else settings.HUMAN_TAKEOVER_IDLE_SECONDS
    takeover_at = _as_utc(row.get("human_takeover_at"))
    last_user_at = _as_utc(row.get("last_user_at"))

    if not _idle_deadline_passed(
        now=now_utc,
        takeover_at=takeover_at,
        last_user_at=last_user_at,
        last_operator_at=last_operator_at,
        idle_seconds=idle,
    ):
        return HumanTakeoverGateResult(
            allows_auto_reply=False,
            released_to_ai=False,
            reason="human_operator_pending",
        )

    released = await release_human_takeover_to_ai(
        db,
        conversation_id,
        reason="idle_timeout",
    )
    if not released:
        return HumanTakeoverGateResult(
            allows_auto_reply=False,
            released_to_ai=False,
            reason="release_race_lost",
        )
    return HumanTakeoverGateResult(
        allows_auto_reply=True,
        released_to_ai=True,
        reason="idle_timeout_released",
    )


async def list_idle_human_takeover_candidates(
    db: AsyncSession,
    *,
    idle_seconds: int | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Conversations in human control whose idle deadline has passed."""
    from services.post_inbound_video_expert_gate import (
        conversation_requires_post_inbound_video_expert,
    )

    idle = idle_seconds if idle_seconds is not None else settings.HUMAN_TAKEOVER_IDLE_SECONDS
    rows = (
        await db.execute(
            text(
                """
                SELECT
                  c.id::text AS conversation_id,
                  c.user_id::text AS user_id,
                  u.external_id AS external_user_id,
                  COALESCE(NULLIF(c.channel, ''), NULLIF(u.channel, ''), 'telegram_real_user') AS platform,
                  COALESCE(
                    (
                      SELECT MAX(ht.locked_at)
                      FROM handoff_tasks ht
                      WHERE ht.conversation_id = c.id
                        AND ht.locked_at IS NOT NULL
                    ),
                    c.updated_at
                  ) AS human_takeover_at,
                  (
                    SELECT MAX(m.created_at)
                    FROM messages m
                    WHERE m.conversation_id = c.id
                      AND m.sender_type = 'user'
                  ) AS last_user_at,
                  (
                    SELECT MAX(m.created_at)
                    FROM messages m
                    WHERE m.conversation_id = c.id
                      AND (
                        m.sender_type = 'operator'
                        OR COALESCE(m.is_operator_message, false) = true
                      )
                  ) AS last_operator_at,
                  (
                    SELECT m.id::text
                    FROM messages m
                    WHERE m.conversation_id = c.id
                      AND m.sender_type = 'user'
                    ORDER BY m.created_at DESC
                    LIMIT 1
                  ) AS last_user_msg_id,
                  (
                    SELECT m.content
                    FROM messages m
                    WHERE m.conversation_id = c.id
                      AND m.sender_type = 'user'
                    ORDER BY m.created_at DESC
                    LIMIT 1
                  ) AS last_user_text,
                  (
                    SELECT m.sender_id
                    FROM messages m
                    WHERE m.conversation_id = c.id
                      AND m.sender_type = 'assistant'
                    ORDER BY m.created_at DESC
                    LIMIT 1
                  ) AS telegram_account_id
                FROM conversations c
                JOIN users u ON u.id = c.user_id
                WHERE c.state IN ('HUMAN_LOCKED', 'WAITING_OPERATOR')
                  AND u.status = 'active'
                  AND NOT EXISTS (
                    SELECT 1 FROM handoff_tasks t1ht
                    WHERE t1ht.conversation_id=c.id
                      AND t1ht.closed_at IS NULL
                      AND t1ht.trigger_reason='t1_country_manual_chat'
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM messages om
                    WHERE om.conversation_id=c.id
                      AND (
                        om.sender_type = 'operator'
                        OR COALESCE(om.is_operator_message, false) = true
                      )
                  )
                ORDER BY c.updated_at ASC
                LIMIT :limit
                """
            ),
            {"limit": max(1, limit)},
        )
    ).mappings().all()

    now = datetime.now(timezone.utc)
    candidates: list[dict[str, Any]] = []
    for row in rows:
        mapping = dict(row)
        if await conversation_requires_post_inbound_video_expert(
            db,
            conversation_id=str(mapping["conversation_id"]),
        ):
            continue
        if not mapping.get("last_user_text"):
            continue
        if not _idle_deadline_passed(
            now=now,
            takeover_at=_as_utc(mapping.get("human_takeover_at")),
            last_user_at=_as_utc(mapping.get("last_user_at")),
            last_operator_at=_as_utc(mapping.get("last_operator_at")),
            idle_seconds=idle,
        ):
            continue
        candidates.append(mapping)
    return candidates
