"""Daily Telegram account health gate for video reinvitations."""

from __future__ import annotations

import asyncio
import time
from uuid import UUID

from loguru import logger
from sqlalchemy import text
from telethon import functions

from core.database import AsyncSessionLocal
from services.telegram_account_manager import telegram_account_manager

LOCK_KEY = 82640117
BAN_TOKENS = (
    "auth_key_unregistered",
    "authkeyunregistered",
    "session_revoked",
    "sessionrevoked",
    "user_deactivated",
    "userdeactivated",
    "phone_number_banned",
    "phonenumberbanned",
    "account banned",
    "cross_account_user_deleted",
    "usernamenotoccupied",
    "username not occupied",
)
RESTRICT_TOKENS = ("peerflood", "floodwait", "spam", "restricted")


def _classify(error: str) -> str:
    lowered = error.lower()
    if any(x in lowered for x in BAN_TOKENS):
        return "banned"
    if any(x in lowered for x in RESTRICT_TOKENS):
        return "restricted"
    return "pending_recheck"


async def run_health_check(run_type: str = "scheduled") -> dict[str, int]:
    async with AsyncSessionLocal() as db:
        locked = (await db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY})).scalar()
        if not locked:
            return {"skipped": 1}
        try:
            run_id = (await db.execute(text("INSERT INTO telegram_account_health_runs(run_type) VALUES(:kind) RETURNING id::text"), {"kind": run_type})).scalar_one()
            rows = (await db.execute(text("""SELECT a.id::text,a.status,a.error_message,a.created_at,
              a.username,a.user_id,
              a.created_at>=NOW()-INTERVAL '3 days' is_new
              FROM telegram_accounts a WHERE a.is_active ORDER BY a.created_at"""))).mappings().all()
            counts = {"checked": 0, "healthy": 0, "new": 0, "pending": 0, "banned": 0}
            skipped = 0
            banned_account_ids: list[str] = []
            verifier_ids = list(telegram_account_manager.clients.keys())
            for index, row in enumerate(rows):
                account_id = UUID(row["id"])
                from services.runtime_ownership import this_process_may_hold_telegram_session

                if not await this_process_may_hold_telegram_session(str(account_id)):
                    skipped += 1
                    continue
                client = await telegram_account_manager.get_client(account_id)
                state, error = "pending_recheck", str(row["error_message"] or "")
                try:
                    # The database status and a cached client object do not prove
                    # that the MTProto socket is live.  Restore the connection
                    # before running the account capability probes.
                    if client is None or not client.is_connected():
                        reconnected = await asyncio.wait_for(
                            telegram_account_manager.connect_account(account_id),
                            timeout=20,
                        )
                        client = (
                            await telegram_account_manager.get_client(account_id)
                            if reconnected
                            else None
                        )
                    if (
                        client is not None
                        and client.is_connected()
                        and await asyncio.wait_for(client.is_user_authorized(), timeout=10)
                    ):
                        await asyncio.wait_for(client.get_me(), timeout=10)
                        # ``get_me`` may still succeed from an authorized session on an
                        # account that Telegram has frozen. This account-scoped, read-only
                        # RPC forces Telegram to validate the account against the server.
                        await asyncio.wait_for(
                            client(functions.account.GetAuthorizationsRequest()),
                            timeout=10,
                        )
                        state, error = "healthy", ""
                        username = str(row["username"] or "").strip().lstrip("@")
                        if username and len(verifier_ids) > 1:
                            verifier_id = verifier_ids[(index + 1) % len(verifier_ids)]
                            if verifier_id == account_id:
                                verifier_id = verifier_ids[(index + 2) % len(verifier_ids)]
                            verifier = await telegram_account_manager.get_client(verifier_id)
                            if verifier is not None:
                                try:
                                    entity = await asyncio.wait_for(
                                        verifier.get_entity(username), timeout=10
                                    )
                                    if bool(getattr(entity, "deleted", False)):
                                        state, error = "banned", "cross_account_user_deleted"
                                    expected_user_id = row["user_id"]
                                    resolved_user_id = getattr(entity, "id", None)
                                    if (
                                        state == "healthy"
                                        and expected_user_id is not None
                                        and resolved_user_id is not None
                                        and int(expected_user_id) != int(resolved_user_id)
                                    ):
                                        state = "pending_recheck"
                                        error = "cross_account_user_id_mismatch"
                                except Exception as cross_exc:
                                    cross_error = f"{type(cross_exc).__name__}: {cross_exc}"[:500]
                                    cross_lower = cross_error.lower()
                                    if "usernamenotoccupied" in cross_lower or "username not occupied" in cross_lower:
                                        state, error = "banned", cross_error

                        # Final capability probe: frozen accounts can pass every read-only
                        # RPC. Send only to the account's own Saved Messages and delete the
                        # probe immediately, so no customer or third party is contacted.
                        if state == "healthy":
                            probe = await asyncio.wait_for(
                                client.send_message("me", "ERIS_ACCOUNT_HEALTH_PROBE"),
                                timeout=10,
                            )
                            await asyncio.wait_for(
                                client.delete_messages("me", [probe.id], revoke=True),
                                timeout=10,
                            )
                    elif error:
                        state = _classify(error)
                    else:
                        error = "runtime_client_unavailable"
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"[:500]
                    state = _classify(error)
                is_new = bool(row["is_new"])
                counts["checked"] += 1
                counts["new"] += int(bool(is_new))
                counts["healthy" if state == "healthy" else "banned" if state == "banned" else "pending"] += 1
                await db.execute(text("""INSERT INTO video_reinvite_account_state
                  (account_id,status,platform_connected_at,first_connected_at,is_new_account,health_check_status,last_health_check_at,last_health_error,health_check_attempts)
                  VALUES(CAST(:id AS uuid),'active',:created,:created,:new,:health,NOW(),NULLIF(:error,''),1)
                  ON CONFLICT(account_id) DO UPDATE SET
                    health_check_status=:health,last_health_check_at=NOW(),last_health_error=NULLIF(:error,''),
                    health_check_attempts=CASE WHEN :health='healthy' THEN 0 ELSE video_reinvite_account_state.health_check_attempts+1 END,
                    consecutive_failures=CASE WHEN :health='healthy' THEN 0 ELSE video_reinvite_account_state.consecutive_failures END,
                    is_new_account=:new,
                    status=CASE WHEN :health='banned' THEN 'paused' ELSE video_reinvite_account_state.status END,
                    paused_at=CASE WHEN :health='banned' THEN NOW() ELSE video_reinvite_account_state.paused_at END,
                    pause_reason=CASE WHEN :health='banned' THEN 'telegram_account_banned' ELSE video_reinvite_account_state.pause_reason END,
                    updated_at=NOW()"""), {"id":row["id"],"created":row["created_at"],"new":is_new,"health":state,"error":error})
                if state == "banned":
                    banned_account_ids.append(str(row["id"]))
            await db.execute(text("""UPDATE telegram_account_health_runs SET completed_at=NOW(),checked_count=:checked,
              healthy_count=:healthy,new_count=:new,pending_count=:pending,banned_count=:banned WHERE id=CAST(:id AS uuid)"""), {**counts,"id":run_id})
            await db.commit()
            # Do not lock the live reinvite queue inside the long health-scan
            # transaction; the sender worker may own the same rows.
            for account_id in banned_account_ids:
                try:
                    await db.execute(text("""UPDATE video_reinvite_jobs SET status='waiting_migration',next_send_at=NULL,
                      stopped_reason='telegram_account_banned',updated_at=NOW()
                      WHERE account_id=CAST(:id AS uuid) AND status IN ('scheduled','sent','restricted','sending')"""), {"id":account_id})
                    await db.commit()
                except Exception:
                    await db.rollback()
                    logger.bind(account_id=account_id).exception("telegram_account_health.pause_jobs_failed")
            logger.bind(**counts, skipped=skipped, run_type=run_type).info("telegram_account_health.completed")
            return counts
        finally:
            try:
                await db.rollback()
                await db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception("telegram_account_health.unlock_failed")


async def queue_health_check(run_type: str = "manual") -> dict[str, object]:
    """Run locally on Runtime/all; API enqueues so the probe uses live sessions."""
    from core.config import settings
    from core.process_role import normalize_process_role

    role = normalize_process_role(getattr(settings, "PROCESS_ROLE", "all"))
    if role in {"telegram_runtime", "all"}:
        asyncio.create_task(run_health_check(run_type))
        return {"ok": True, "started": True, "via": "local"}

    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    """
                    SELECT account_id::text, generation
                    FROM telegram_account_ownership
                    WHERE owner = 'runtime'
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                )
            )
        ).first()
    if row is None:
        asyncio.create_task(run_health_check(run_type))
        return {"ok": True, "started": True, "via": "local_fallback"}

    from services.telegram_command_gateway import enqueue_runtime_command

    command_id = await enqueue_runtime_command(
        command_type="account_health_check",
        account_id=str(row[0]),
        payload={"run_type": run_type},
        generation=int(row[1] or 0),
        idempotency_key=f"account_health_check:{run_type}:{int(time.time()) // 60}",
    )
    return {"ok": True, "started": True, "via": "runtime", "command_id": command_id}
