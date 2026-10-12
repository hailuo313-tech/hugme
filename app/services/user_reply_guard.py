"""Guards for blocking auto-reply to frozen or inactive users."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

BLOCKED_USER_STATUSES = frozenset({"frozen", "blocked_minor", "deleted"})
BLOCKED_CONVERSATION_STATES = frozenset({"FROZEN", "CLOSED", "ESCALATED"})


async def fetch_user_status(db: AsyncSession, user_id: str) -> str:
    row = (
        await db.execute(
            text("SELECT status FROM users WHERE id = :uid"),
            {"uid": user_id},
        )
    ).fetchone()
    if not row:
        return "missing"
    return str(row[0] or "active")


async def user_allows_auto_reply(db: AsyncSession, user_id: str) -> bool:
    return (await fetch_user_status(db, user_id)) == "active"


async def conversation_allows_auto_reply(db: AsyncSession, conversation_id: str) -> bool:
    row = (
        await db.execute(
            text("SELECT state FROM conversations WHERE id = :cid"),
            {"cid": conversation_id},
        )
    ).fetchone()
    if not row:
        return False
    return str(row[0] or "") not in BLOCKED_CONVERSATION_STATES
