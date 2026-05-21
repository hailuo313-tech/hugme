"""S/A suspension service for P3-16: S/A hang + draft with Top3 scripts."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import AsyncSessionLocal
from services.script_template_retriever import (
    ScriptTemplateHit,
    ScriptTemplateQuery,
    search_script_templates,
)


async def check_user_level(db: AsyncSession, user_id: str) -> Optional[str]:
    """Check user level from database."""
    result = await db.execute(
        text("SELECT level FROM users WHERE id = :user_id"),
        {"user_id": user_id}
    )
    row = result.fetchone()
    return row[0] if row else None


async def generate_draft_scripts(
    db: AsyncSession,
    user_id: str,
    user_level: str,
    query_text: str,
    platform: str = "telegram_real_user",
    trace_id: Optional[str] = None,
) -> tuple[list[ScriptTemplateHit], list[str]]:
    """Generate Top3 script recommendations for draft.

    Returns:
        Tuple of (script hits, script IDs)
    """
    try:
        # Search for script templates
        query = ScriptTemplateQuery(
            query=query_text,
            platform=platform,
            user_level=user_level,
            hook="operator",  # Use operator hook for handoff scenarios
            limit=3,
        )

        search_result = await search_script_templates(
            db=db,
            query=query,
            trace_id=trace_id,
        )

        hits = search_result.hits
        script_ids = [hit.id for hit in hits]

        logger.bind(
            trace_id=trace_id,
            user_id=user_id,
            user_level=user_level,
            hits_count=len(hits),
        ).info("suspension_service.draft_generated")

        return hits, script_ids

    except Exception as e:
        logger.bind(
            trace_id=trace_id,
            user_id=user_id,
        ).error(f"suspension_service.draft_error: {e}")
        return [], []


async def create_handoff_draft(
    db: AsyncSession,
    task_id: str,
    query_text: str,
    countdown_seconds: int = 120,
    trace_id: Optional[str] = None,
) -> dict[str, Any]:
    """Create draft for handoff task with Top3 script recommendations.

    Args:
        db: Database session
        task_id: Handoff task ID
        query_text: Query text for script search
        countdown_seconds: Countdown duration in seconds
        trace_id: Trace ID for logging

    Returns:
        Dict with draft information
    """
    try:
        # Get task information
        result = await db.execute(
            text("""
                SELECT ht.id, ht.user_id, u.level, u.channel
                FROM handoff_tasks ht
                JOIN users u ON ht.user_id = u.id
                WHERE ht.id = :task_id
            """),
            {"task_id": task_id}
        )
        task = result.fetchone()
        if not task:
            raise ValueError(f"Handoff task {task_id} not found")

        task_id_str = str(task[0])
        user_id_str = str(task[1])
        user_level = task[2]
        platform = task[3] or "telegram_real_user"

        # Check if user is S or A level
        if user_level not in ['S', 'A']:
            logger.bind(
                trace_id=trace_id,
                task_id=task_id,
                user_level=user_level,
            ).warning("suspension_service.not_sa_level")
            return {
                "success": False,
                "reason": "User is not S or A level",
                "user_level": user_level,
            }

        # Generate Top3 script recommendations
        hits, script_ids = await generate_draft_scripts(
            db=db,
            user_id=user_id_str,
            user_level=user_level,
            query_text=query_text,
            platform=platform,
            trace_id=trace_id,
        )

        # Calculate draft expiration
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=countdown_seconds)

        # Build draft content
        draft_content = _build_draft_content(hits)

        # Update handoff task with draft information
        await db.execute(
            text("""
                UPDATE handoff_tasks
                SET draft_content = :draft_content,
                    draft_script_ids = :script_ids,
                    draft_created_at = :created_at,
                    draft_expires_at = :expires_at,
                    countdown_seconds = :countdown,
                    updated_at = NOW()
                WHERE id = :task_id
            """),
            {
                "task_id": task_id,
                "draft_content": draft_content,
                "script_ids": script_ids,
                "created_at": now,
                "expires_at": expires_at,
                "countdown": countdown_seconds,
            }
        )
        await db.commit()

        logger.bind(
            trace_id=trace_id,
            task_id=task_id,
            script_count=len(script_ids),
            expires_at=expires_at,
        ).info("suspension_service.draft_created")

        return {
            "success": True,
            "task_id": task_id_str,
            "user_id": user_id_str,
            "user_level": user_level,
            "draft_content": draft_content,
            "script_ids": script_ids,
            "script_hits": [
                {
                    "id": hit.id,
                    "title": hit.title,
                    "content": hit.content,
                    "similarity": hit.similarity,
                }
                for hit in hits
            ],
            "countdown_seconds": countdown_seconds,
            "draft_created_at": now.isoformat(),
            "draft_expires_at": expires_at.isoformat(),
        }

    except Exception as e:
        logger.bind(
            trace_id=trace_id,
            task_id=task_id,
        ).error(f"suspension_service.create_draft_error: {e}")
        await db.rollback()
        return {
            "success": False,
            "reason": str(e),
        }


def _build_draft_content(hits: list[ScriptTemplateHit]) -> str:
    """Build draft content from script hits.

    Format:
    推荐话术 Top3：
    1. [话术标题]
       [话术内容]
    2. [话术标题]
       [话术内容]
    3. [话术标题]
       [话术内容]
    """
    if not hits:
        return "暂无推荐话术"

    lines = ["推荐话术 Top3："]
    for i, hit in enumerate(hits, 1):
        lines.append(f"{i}. {hit.title or '无标题'}")
        lines.append(f"   {hit.content}")
        if hit.similarity is not None:
            lines.append(f"   相似度: {hit.similarity:.2f}")
        lines.append("")  # Empty line between scripts

    return "\n".join(lines)


async def get_draft_with_countdown(
    db: AsyncSession,
    task_id: str,
    trace_id: Optional[str] = None,
) -> dict[str, Any]:
    """Get draft information with remaining countdown.

    Args:
        db: Database session
        task_id: Handoff task ID
        trace_id: Trace ID for logging

    Returns:
        Dict with draft information and remaining countdown
    """
    try:
        result = await db.execute(
            text("""
                SELECT
                    id,
                    draft_content,
                    draft_script_ids,
                    draft_created_at,
                    draft_expires_at,
                    countdown_seconds,
                    status
                FROM handoff_tasks
                WHERE id = :task_id
            """),
            {"task_id": task_id}
        )
        task = result.fetchone()
        if not task:
            raise ValueError(f"Handoff task {task_id} not found")

        draft_content = task[1]
        script_ids = task[2]
        draft_created_at = task[3]
        draft_expires_at = task[4]
        countdown_seconds = task[5]
        status = task[6]

        if not draft_content or not draft_expires_at:
            return {
                "success": True,
                "has_draft": False,
                "task_id": task_id,
                "status": status,
            }

        # Calculate remaining countdown
        now = datetime.now(timezone.utc)
        if draft_expires_at.tzinfo is None:
            draft_expires_at = draft_expires_at.replace(tzinfo=timezone.utc)

        remaining_seconds = max(0, int((draft_expires_at - now).total_seconds()))
        is_expired = remaining_seconds == 0

        return {
            "success": True,
            "has_draft": True,
            "task_id": task_id,
            "status": status,
            "draft_content": draft_content,
            "script_ids": script_ids,
            "countdown_seconds": countdown_seconds,
            "remaining_seconds": remaining_seconds,
            "is_expired": is_expired,
            "draft_created_at": draft_created_at.isoformat() if draft_created_at else None,
            "draft_expires_at": draft_expires_at.isoformat() if draft_expires_at else None,
        }

    except Exception as e:
        logger.bind(
            trace_id=trace_id,
            task_id=task_id,
        ).error(f"suspension_service.get_draft_error: {e}")
        return {
            "success": False,
            "reason": str(e),
        }


async def suspend_sa_message(
    db: AsyncSession,
    conversation_id: str,
    query_text: str,
    trigger_reason: str = "SA_LEVEL_AUTO_SUSPEND",
    countdown_seconds: int = 120,
    trace_id: Optional[str] = None,
) -> dict[str, Any]:
    """Suspend message for S/A level user and create handoff task with draft.

    Args:
        db: Database session
        conversation_id: Conversation ID
        query_text: Query text for script search
        trigger_reason: Reason for suspension
        countdown_seconds: Countdown duration in seconds
        trace_id: Trace ID for logging

    Returns:
        Dict with suspension result
    """
    try:
        # Get conversation and user information
        result = await db.execute(
            text("""
                SELECT c.id, c.user_id, u.level, u.channel
                FROM conversations c
                JOIN users u ON c.user_id = u.id
                WHERE c.id = :conversation_id
            """),
            {"conversation_id": conversation_id}
        )
        conv = result.fetchone()
        if not conv:
            raise ValueError(f"Conversation {conversation_id} not found")

        conv_id_str = str(conv[0])
        user_id_str = str(conv[1])
        user_level = conv[2]

        # Check if user is S or A level
        if user_level not in ['S', 'A']:
            logger.bind(
                trace_id=trace_id,
                conversation_id=conversation_id,
                user_level=user_level,
            ).warning("suspension_service.not_sa_level_skip")
            return {
                "success": False,
                "reason": "User is not S or A level",
                "user_level": user_level,
            }

        # Check if handoff task already exists
        existing_task = await db.execute(
            text("""
                SELECT id, status
                FROM handoff_tasks
                WHERE conversation_id = :conversation_id
                AND status IN ('pending', 'HUMAN_LOCKED')
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"conversation_id": conversation_id}
        )
        existing = existing_task.fetchone()

        if existing:
            task_id_str = str(existing[0])
            # Update existing task with new draft
            draft_result = await create_handoff_draft(
                db=db,
                task_id=task_id_str,
                query_text=query_text,
                countdown_seconds=countdown_seconds,
                trace_id=trace_id,
            )
            return {
                "success": True,
                "action": "updated_existing_task",
                "task_id": task_id_str,
                "draft": draft_result,
            }

        # Create new handoff task
        new_task_id = str(uuid4())

        await db.execute(
            text("""
                INSERT INTO handoff_tasks (
                    id, user_id, conversation_id, priority, trigger_reason, status
                ) VALUES (
                    :id, :user_id, :conversation_id, 'P1', :trigger_reason, 'pending'
                )
            """),
            {
                "id": new_task_id,
                "user_id": user_id_str,
                "conversation_id": conv_id_str,
                "trigger_reason": trigger_reason,
            }
        )

        # Create draft for the new task
        draft_result = await create_handoff_draft(
            db=db,
            task_id=new_task_id,
            query_text=query_text,
            countdown_seconds=countdown_seconds,
            trace_id=trace_id,
        )

        await db.commit()

        logger.bind(
            trace_id=trace_id,
            conversation_id=conversation_id,
            task_id=new_task_id,
            user_level=user_level,
        ).info("suspension_service.suspended")

        return {
            "success": True,
            "action": "created_new_task",
            "task_id": new_task_id,
            "conversation_id": conv_id_str,
            "user_id": user_id_str,
            "user_level": user_level,
            "draft": draft_result,
        }

    except Exception as e:
        logger.bind(
            trace_id=trace_id,
            conversation_id=conversation_id,
        ).error(f"suspension_service.suspend_error: {e}")
        await db.rollback()
        return {
            "success": False,
            "reason": str(e),
        }
