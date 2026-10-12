"""Shared health gate for every proactive Telegram sender."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text


async def check_outbound_account(
    db: Any,
    account_id: str | None,
    *,
    allow_operator_reply: bool = False,
) -> tuple[bool, str, datetime | None]:
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
    if row["health_check_status"] == "banned":
        return False, "account_banned", row["resume_at"]
    if allow_operator_reply:
        # Human replies in an existing chat are not cold outreach.
        return True, "operator_allowed", None
    if row["health_status"] and row["health_status"] != "active":
        return False, f"account_{row['health_status']}", row["resume_at"]
    if row["health_check_status"] and row["health_check_status"] != "healthy":
        return False, f"account_{row['health_check_status']}", row["resume_at"]
    if row["resume_at"] and row["resume_at"] > datetime.now(row["resume_at"].tzinfo):
        return False, "account_cooldown", row["resume_at"]
    return True, "active", None


async def pause_outbound_account(db: Any, account_id: str, *, reason: str, hours: int = 24) -> None:
    prior_restrictions = int((await db.execute(text("""
        SELECT COUNT(*) FROM runtime_commands WHERE account_id=CAST(:account_id AS uuid)
          AND error IN ('PeerFloodError','UserRestrictedError')
          AND created_at>=NOW()-INTERVAL '30 days'
    """), {"account_id": account_id})).scalar() or 0)
    hours = 168 if prior_restrictions >= 2 else 48 if prior_restrictions >= 1 else max(24, hours)
    await db.execute(text("""
        INSERT INTO video_reinvite_account_state
          (account_id,status,health_check_status,pause_reason,resume_at,last_peer_flood_at,updated_at)
        VALUES (CAST(:account_id AS uuid),'paused','restricted',:reason,
                NOW()+make_interval(hours=>:hours),NOW(),NOW())
        ON CONFLICT(account_id) DO UPDATE SET status='paused',health_check_status='restricted',
          pause_reason=EXCLUDED.pause_reason,resume_at=EXCLUDED.resume_at,
          last_peer_flood_at=NOW(),updated_at=NOW()
    """), {"account_id": account_id, "reason": reason[:500], "hours": max(1, hours)})

async def check_recovery_send_quota(db: Any, account_id: str) -> tuple[bool, str, datetime | None]:
    row = (await db.execute(text("""SELECT pause_reason,effective_min_interval_seconds
        FROM video_reinvite_account_state WHERE account_id=CAST(:account_id AS uuid)"""),
        {"account_id": account_id})).mappings().first()
    if not row or not str(row.get("pause_reason") or "").startswith("recovery_limited_stage_"):
        return True, "normal", None
    stage = str(row["pause_reason"])[-1]
    hourly_limit = {"1": 2, "2": 4, "3": 8}.get(stage, 2)
    minimum_seconds = int(row.get("effective_min_interval_seconds") or 1200)
    usage = (await db.execute(text("""SELECT
        COUNT(*) FILTER(WHERE completed_at>=NOW()-INTERVAL '1 hour') AS hourly,
        MAX(completed_at) AS last_sent FROM runtime_commands
        WHERE account_id=CAST(:account_id AS uuid)
          AND command_type IN ('send_message','send_media') AND status='succeeded'"""),
        {"account_id": account_id})).mappings().one()
    now = datetime.now(usage["last_sent"].tzinfo) if usage["last_sent"] else datetime.now().astimezone()
    if int(usage["hourly"] or 0) >= hourly_limit:
        return False, "account_recovery_hourly_limit", now + timedelta(hours=1)
    if usage["last_sent"] is not None:
        next_at = usage["last_sent"] + timedelta(seconds=minimum_seconds)
        if next_at > now:
            return False, "account_recovery_interval", next_at
    return True, "recovery_allowed", None
