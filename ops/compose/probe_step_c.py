"""Step C probe: refuse live switches; dry-run only; ownership table stays 0."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from core.database import AsyncSessionLocal
from services.runtime_account_switch import (
    apply_account_switch,
    rollback_account_to_legacy,
    _write_runtime_ownership,
)
from services.runtime_ownership import reset_ownership_runtime_state


async def _one(sql: str, **params):
    async with AsyncSessionLocal() as db:
        return (await db.execute(text(sql), params)).scalar()


async def main() -> None:
    reset_ownership_runtime_state()
    refused = await apply_account_switch("00000000-0000-4000-8000-000000000001")
    if refused.get("ok") or "canary_disabled" not in (refused.get("reasons") or []):
        raise SystemExit(f"canary off must refuse: {refused}")
    if refused.get("wrote_ownership"):
        raise SystemExit("disabled apply must not write ownership")

    banned = await _one(
        """
        SELECT id::text FROM telegram_accounts
        WHERE status = 'banned'
        ORDER BY updated_at DESC
        LIMIT 1
        """
    )
    if not banned:
        raise SystemExit("no banned account")
    banned_plan = await apply_account_switch(
        banned,
        dry_run=True,
        canary_enabled=True,
        allow_canary_override=True,
    )
    if banned_plan.get("ok"):
        raise SystemExit(f"banned/unhealthy account must not be switchable: {banned_plan}")
    if "unhealthy" not in (banned_plan.get("reasons") or []):
        raise SystemExit(f"banned reasons should include unhealthy: {banned_plan}")

    connected = await _one(
        """
        SELECT a.id::text
        FROM telegram_accounts a
        WHERE a.status = 'connected'
          AND COALESCE(a.is_active, false) = true
          AND a.session_string IS NOT NULL
          AND length(a.session_string) > 20
          AND NOT EXISTS (
              SELECT 1 FROM call_broadcast_jobs j
              WHERE j.account_id = a.id
                AND j.status IN ('queued', 'claimed', 'calling', 'ringing', 'active', 'streaming', 'pending_operator')
          )
        ORDER BY a.updated_at DESC
        LIMIT 1
        """
    )
    if not connected:
        raise SystemExit("no connected account for dry-run")
    planned = await apply_account_switch(
        connected,
        dry_run=True,
        canary_enabled=True,
        allow_canary_override=True,
    )
    if planned.get("wrote_ownership") or planned.get("execute"):
        raise SystemExit("dry-run must not execute or write")
    if planned.get("ok"):
        if not planned.get("dry_run"):
            raise SystemExit(f"successful plan must stay dry-run: {planned}")
        would = planned.get("would") or {}
        if not would.get("legacy_disconnect") or not would.get("write_owner_runtime"):
            raise SystemExit(f"dry-run must list disconnect+write: {planned}")
    elif not planned.get("reasons"):
        raise SystemExit(f"failed dry-run must explain: {planned}")

    executed = await apply_account_switch(connected, dry_run=False, execute=True)
    if executed.get("ok") or "canary_disabled" not in (executed.get("reasons") or []):
        raise SystemExit(f"execute without canary flag must refuse: {executed}")
    if executed.get("wrote_ownership"):
        raise SystemExit("execute without canary must not write")

    await _write_runtime_ownership(banned, 2, "switching")
    await rollback_account_to_legacy(banned)
    leftover = await _one("SELECT count(*)::int FROM telegram_account_ownership")
    if leftover != 0:
        raise SystemExit(f"ownership not cleaned: {leftover}")

    sending_block = await apply_account_switch(
        connected,
        dry_run=True,
        canary_enabled=True,
        allow_canary_override=True,
        metrics={"auth_key_duplicated": 1},
    )
    if sending_block.get("ok") or sending_block.get("reasons") != ["AuthKeyDuplicated"]:
        raise SystemExit(f"red line must abort: {sending_block}")

    print("stepC probe passed", connected, banned)


if __name__ == "__main__":
    asyncio.run(main())
