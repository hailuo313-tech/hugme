"""Route post–auto-inbound-video users to expert (human) takeover only."""

from __future__ import annotations

import uuid

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from services.call_broadcast.jobs import count_completed_inbound_auto_answer_calls_for_chat
from services.call_broadcast.jobs import count_inbound_call_events_for_chat
from services.human_takeover_gate import HUMAN_CONTROL_STATES

POST_INBOUND_VIDEO_HANDOFF_TRIGGER = "post_inbound_video:auto_seq_complete"
_OPEN_HANDOFF_STATUSES = (
    "pending",
    "PENDING",
    "ESCALATED",
    "HUMAN_LOCKED",
    "WAITING_OPERATOR",
)


def post_inbound_video_expert_threshold() -> int:
    return max(1, int(getattr(settings, "CALL_BROADCAST_INBOUND_MANUAL_AFTER", 2)))


def post_inbound_video_expert_only_enabled() -> bool:
    return bool(getattr(settings, "POST_INBOUND_VIDEO_EXPERT_ONLY_ENABLED", True))


def post_inbound_video_release_review_calls() -> int:
    return max(1, int(getattr(settings, "POST_INBOUND_VIDEO_RELEASE_REVIEW_CALLS", 6)))


async def inbound_calls_reached_release_review(db: AsyncSession, chat_id: int) -> bool:
    return (
        await count_inbound_call_events_for_chat(db, int(chat_id))
        >= post_inbound_video_release_review_calls()
    )


async def resolve_chat_id_for_user(db: AsyncSession, user_id: str) -> int | None:
    row = (
        await db.execute(
            text("SELECT external_id FROM users WHERE id = CAST(:uid AS uuid)"),
            {"uid": user_id},
        )
    ).fetchone()
    if not row or not row[0]:
        return None
    external_id = str(row[0])
    if not external_id.startswith("tg_"):
        return None
    try:
        return int(external_id[3:])
    except ValueError:
        return None


async def requires_post_inbound_video_expert(
    db: AsyncSession,
    *,
    chat_id: int,
) -> bool:
    if not post_inbound_video_expert_only_enabled():
        return False
    completed = await count_completed_inbound_auto_answer_calls_for_chat(db, int(chat_id))
    return completed >= post_inbound_video_expert_threshold()


async def is_post_inbound_video_expert_waived(
    db: AsyncSession,
    conversation_id: str,
) -> bool:
    row = (
        await db.execute(
            text(
                """
                SELECT post_inbound_video_expert_waived_at
                FROM conversations
                WHERE id = CAST(:cid AS uuid)
                """
            ),
            {"cid": conversation_id},
        )
    ).fetchone()
    return bool(row and row[0] is not None)


async def has_open_post_inbound_video_handoff(
    db: AsyncSession,
    conversation_id: str,
) -> bool:
    row = (
        await db.execute(
            text(
                """
                SELECT 1
                FROM handoff_tasks
                WHERE conversation_id = CAST(:cid AS uuid)
                  AND closed_at IS NULL
                  AND trigger_reason = :trigger_reason
                  AND status = ANY(:statuses)
                LIMIT 1
                """
            ),
            {
                "cid": conversation_id,
                "trigger_reason": POST_INBOUND_VIDEO_HANDOFF_TRIGGER,
                "statuses": list(_OPEN_HANDOFF_STATUSES),
            },
        )
    ).fetchone()
    return row is not None


async def conversation_release_eligible(
    db: AsyncSession,
    conversation_id: str,
) -> bool:
    row = (
        await db.execute(
            text(
                """
                SELECT c.state, c.post_inbound_video_expert_waived_at,
                       u.external_id, u.status,
                       UPPER(COALESCE(NULLIF(p.user_level, ''), '')) AS user_level,
                       COALESCE(p.vip_level, 0) AS vip_level
                FROM conversations c
                JOIN users u ON u.id = c.user_id
                LEFT JOIN user_profiles p ON p.user_id = u.id
                WHERE c.id = CAST(:cid AS uuid)
                """
            ),
            {"cid": conversation_id},
        )
    ).fetchone()
    if not row:
        return False
    state = str(row[0] or "")
    if state not in ("WAITING_OPERATOR", "HUMAN_LOCKED"):
        return False
    if row[1] is not None:
        return False
    if str(row[3] or "") == "frozen":
        return False
    if str(row[4] or "") in ("S", "A") or int(row[5] or 0) >= 2:
        return False
    external_id = str(row[2] or "")
    try:
        chat_id = int(external_id[3:]) if external_id.startswith("tg_") else None
    except ValueError:
        chat_id = None
    if chat_id is None or not await inbound_calls_reached_release_review(db, chat_id):
        return False
    return await has_open_post_inbound_video_handoff(db, conversation_id)


async def resolve_chat_id_for_user_by_conversation(
    db: AsyncSession, conversation_id: str
) -> int | None:
    row = (await db.execute(
        text("""SELECT u.external_id FROM conversations c
                JOIN users u ON u.id = c.user_id
                WHERE c.id = CAST(:cid AS uuid)"""),
        {"cid": conversation_id},
    )).first()
    external_id = str(row[0] or "") if row else ""
    if not external_id.startswith("tg_"):
        return None
    try:
        return int(external_id[3:])
    except ValueError:
        return None


async def ensure_release_review_after_inbound_call(
    db: AsyncSession, *, chat_id: int, trace_id: str | None = None
) -> bool:
    """At the sixth independent ring, put a normal user into release review."""
    if not await inbound_calls_reached_release_review(db, chat_id):
        return False
    row = (await db.execute(
        text("""SELECT u.id::text AS user_id, c.id::text AS conversation_id, u.status,
                       UPPER(COALESCE(NULLIF(p.user_level, ''), '')) AS user_level,
                       COALESCE(p.vip_level, 0) AS vip_level,
                       c.post_inbound_video_expert_waived_at
                FROM users u
                JOIN conversations c ON c.user_id = u.id
                LEFT JOIN user_profiles p ON p.user_id = u.id
                WHERE u.external_id = :external_id
                ORDER BY c.last_message_at DESC NULLS LAST, c.created_at DESC
                LIMIT 1"""),
        {"external_id": f"tg_{int(chat_id)}"},
    )).mappings().one_or_none()
    if not row or row["status"] == "frozen" or row["post_inbound_video_expert_waived_at"] is not None:
        return False
    if str(row["user_level"] or "") in ("S", "A") or int(row["vip_level"] or 0) >= 2:
        return False
    await _ensure_expert_handoff(
        db,
        user_id=str(row["user_id"]),
        conversation_id=str(row["conversation_id"]),
        trace_id=trace_id,
    )
    return True


async def conversation_relock_eligible(
    db: AsyncSession,
    conversation_id: str,
) -> bool:
    if not await is_post_inbound_video_expert_waived(db, conversation_id):
        return False
    row = (
        await db.execute(
            text(
                """
                SELECT u.external_id
                FROM conversations c
                JOIN users u ON u.id = c.user_id
                WHERE c.id = CAST(:cid AS uuid)
                """
            ),
            {"cid": conversation_id},
        )
    ).fetchone()
    if not row or not row[0] or not str(row[0]).startswith("tg_"):
        return False
    try:
        chat_id = int(str(row[0])[3:])
    except ValueError:
        return False
    return await requires_post_inbound_video_expert(db, chat_id=chat_id)


async def conversation_requires_post_inbound_video_expert(
    db: AsyncSession,
    *,
    conversation_id: str,
    chat_id: int | None = None,
) -> bool:
    if await is_post_inbound_video_expert_waived(db, conversation_id):
        return False
    resolved_chat_id = chat_id
    if resolved_chat_id is None:
        row = (
            await db.execute(
                text(
                    """
                    SELECT u.external_id
                    FROM conversations c
                    JOIN users u ON u.id = c.user_id
                    WHERE c.id = CAST(:cid AS uuid)
                    """
                ),
                {"cid": conversation_id},
            )
        ).fetchone()
        if row and row[0] and str(row[0]).startswith("tg_"):
            try:
                resolved_chat_id = int(str(row[0])[3:])
            except ValueError:
                resolved_chat_id = None
    if resolved_chat_id is None:
        return False
    return await requires_post_inbound_video_expert(db, chat_id=int(resolved_chat_id))


async def _has_open_handoff(db: AsyncSession, conversation_id: str) -> bool:
    row = (
        await db.execute(
            text(
                """
                SELECT 1
                FROM handoff_tasks
                WHERE conversation_id = CAST(:cid AS uuid)
                  AND closed_at IS NULL
                  AND status = ANY(:statuses)
                LIMIT 1
                """
            ),
            {"cid": conversation_id, "statuses": list(_OPEN_HANDOFF_STATUSES)},
        )
    ).fetchone()
    return row is not None


async def _ensure_expert_handoff(
    db: AsyncSession,
    *,
    user_id: str,
    conversation_id: str,
    trace_id: str | None,
) -> None:
    state_row = (
        await db.execute(
            text("SELECT state FROM conversations WHERE id = CAST(:cid AS uuid)"),
            {"cid": conversation_id},
        )
    ).fetchone()
    state = str(state_row[0] or "") if state_row else ""

    if state in HUMAN_CONTROL_STATES:
        if await has_open_post_inbound_video_handoff(db, conversation_id):
            return
        task_id = str(uuid.uuid4())
        await db.execute(
            text(
                """
                INSERT INTO handoff_tasks (
                  id, user_id, conversation_id, priority, trigger_reason, status
                ) VALUES (
                  :id, CAST(:uid AS uuid), CAST(:cid AS uuid), 'P1', :tr, 'pending'
                )
                """
            ),
            {
                "id": task_id,
                "uid": user_id,
                "cid": conversation_id,
                "tr": POST_INBOUND_VIDEO_HANDOFF_TRIGGER,
            },
        )
        await db.commit()
        logger.bind(
            trace_id=trace_id,
            component="post_inbound_video_expert_gate",
            user_id=user_id,
            conversation_id=conversation_id,
            conv_state=state,
        ).info("post_inbound_video_expert.handoff_ensured")
        return

    if await _has_open_handoff(db, conversation_id):
        await db.execute(
            text(
                """
                UPDATE conversations
                SET state = 'WAITING_OPERATOR',
                    updated_at = NOW()
                WHERE id = CAST(:cid AS uuid)
                  AND state NOT IN ('HUMAN_LOCKED', 'WAITING_OPERATOR')
                """
            ),
            {"cid": conversation_id},
        )
        await db.commit()
        return

    task_id = str(uuid.uuid4())
    await db.execute(
        text(
            """
            INSERT INTO handoff_tasks (
              id, user_id, conversation_id, priority, trigger_reason, status
            ) VALUES (
              :id, CAST(:uid AS uuid), CAST(:cid AS uuid), 'P1', :tr, 'pending'
            )
            """
        ),
        {
            "id": task_id,
            "uid": user_id,
            "cid": conversation_id,
            "tr": POST_INBOUND_VIDEO_HANDOFF_TRIGGER,
        },
    )

    await db.execute(
        text(
            """
            UPDATE conversations
            SET state = 'WAITING_OPERATOR',
                handoff_count = COALESCE(handoff_count, 0) + 1,
                updated_at = NOW()
            WHERE id = CAST(:cid AS uuid)
            """
        ),
        {"cid": conversation_id},
    )

    await db.commit()
    logger.bind(
        trace_id=trace_id,
        component="post_inbound_video_expert_gate",
        user_id=user_id,
        conversation_id=conversation_id,
        conv_state=state,
    ).info("post_inbound_video_expert.handoff_ensured")


async def block_post_inbound_video_auto_reply(
    db: AsyncSession,
    *,
    user_id: str,
    conversation_id: str,
    chat_id: int | None = None,
    trace_id: str | None = None,
) -> bool:
    """Ensure expert takeover when auto inbound videos are done; True blocks auto-reply."""
    resolved_chat_id = chat_id
    if resolved_chat_id is None:
        resolved_chat_id = await resolve_chat_id_for_user(db, user_id)
    if resolved_chat_id is None:
        return False
    if not await requires_post_inbound_video_expert(db, chat_id=int(resolved_chat_id)):
        return False
    if await is_post_inbound_video_expert_waived(db, conversation_id):
        return False
    await _ensure_expert_handoff(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        trace_id=trace_id,
    )
    return True


async def release_post_inbound_video_expert_to_ai(
    db: AsyncSession,
    *,
    conversation_id: str,
    operator_id: str | None = None,
) -> None:
    if not await conversation_release_eligible(db, conversation_id):
        raise ValueError("conversation_not_eligible_for_post_inbound_video_release")

    await db.execute(
        text(
            """
            UPDATE handoff_tasks
            SET status = 'CLOSED',
                closed_at = COALESCE(closed_at, NOW())
            WHERE conversation_id = CAST(:cid AS uuid)
              AND closed_at IS NULL
              AND trigger_reason = :trigger_reason
              AND status = ANY(:statuses)
            """
        ),
        {
            "cid": conversation_id,
            "trigger_reason": POST_INBOUND_VIDEO_HANDOFF_TRIGGER,
            "statuses": list(_OPEN_HANDOFF_STATUSES),
        },
    )
    await db.execute(
        text(
            """
            UPDATE conversations
            SET state = 'AI_ACTIVE',
                assigned_operator_id = NULL,
                post_inbound_video_expert_waived_at = NOW(),
                updated_at = NOW()
            WHERE id = CAST(:cid AS uuid)
            """
        ),
        {"cid": conversation_id},
    )
    await db.commit()
    logger.bind(
        component="post_inbound_video_expert_gate",
        conversation_id=conversation_id,
        operator_id=operator_id,
    ).info("post_inbound_video_expert.released_to_ai")


async def relock_post_inbound_video_expert(
    db: AsyncSession,
    *,
    user_id: str,
    conversation_id: str,
    operator_id: str | None = None,
    trace_id: str | None = None,
) -> None:
    if not await conversation_relock_eligible(db, conversation_id):
        raise ValueError("conversation_not_eligible_for_post_inbound_video_relock")

    await db.execute(
        text(
            """
            UPDATE conversations
            SET post_inbound_video_expert_waived_at = NULL,
                updated_at = NOW()
            WHERE id = CAST(:cid AS uuid)
            """
        ),
        {"cid": conversation_id},
    )
    await _ensure_expert_handoff(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        trace_id=trace_id,
    )
    logger.bind(
        trace_id=trace_id,
        component="post_inbound_video_expert_gate",
        conversation_id=conversation_id,
        operator_id=operator_id,
    ).info("post_inbound_video_expert.relocked")
