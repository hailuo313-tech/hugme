"""Shared health gate for every proactive Telegram sender."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text


async def check_outbound_account(db: Any, account_id: str | None) -> tuple[bool, str, datetime | None]:
    if not account_id:
        return False, "missing_account", None
    row = (await db.execute(text("""
        SELECT a.status, a.is_active,
               s.status AS health_status, s.health_check_status, s.resume_at
        FROM telegram_accounts a
        LEFT JOIN video_reinvite_account_state s ON s.account_id=a.id
        WHERE a.id=CAST(:account_id AS uuid)
    """), {"account_id": account_id})).mappings().first()
    if not row or row["status"] != "connected" or not row["is_active"]:
        return False, "account_not_connected", None
    if row["health_status"] and row["health_status"] != "active":
        return False, f"account_{row['health_status']}", row["resume_at"]
    if row["health_check_status"] and row["health_check_status"] != "healthy":
        return False, f"account_{row['health_check_status']}", row["resume_at"]
    if row["resume_at"] and row["resume_at"] > datetime.now(row["resume_at"].tzinfo):
        return False, "account_cooldown", row["resume_at"]
    return True, "active", None


async def pause_outbound_account(db: Any, account_id: str, *, reason: str, hours: int = 24) -> None:
    await db.execute(text("""
        INSERT INTO video_reinvite_account_state
          (account_id,status,health_check_status,pause_reason,resume_at,last_peer_flood_at,updated_at)
        VALUES (CAST(:account_id AS uuid),'paused','restricted',:reason,
                NOW()+make_interval(hours=>:hours),NOW(),NOW())
        ON CONFLICT(account_id) DO UPDATE SET status='paused',health_check_status='restricted',
          pause_reason=EXCLUDED.pause_reason,resume_at=EXCLUDED.resume_at,
          last_peer_flood_at=NOW(),updated_at=NOW()
    """), {"account_id": account_id, "reason": reason[:500], "hours": max(1, hours)})
