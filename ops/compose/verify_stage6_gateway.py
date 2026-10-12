"""In-process Stage 6 probe: legacy executes, runtime queues, then cleanup."""

from __future__ import annotations

import asyncio

from services.runtime_ownership import (
    AccountOwnership,
    reset_ownership_runtime_state,
    set_ownership_lookup,
)
from services.telegram_command_gateway import submit_telegram_command


async def main() -> None:
    async def _legacy():
        return "legacy-ok"

    reset_ownership_runtime_state()
    legacy = await submit_telegram_command(
        command_type="shadow_probe",
        account_id=None,
        legacy_execute=_legacy,
    )
    print(
        "LEGACY",
        legacy.owner,
        legacy.status,
        legacy.executed,
        legacy.value,
        legacy.reason,
    )
    if not (legacy.executed and legacy.owner == "legacy" and legacy.value == "legacy-ok"):
        raise SystemExit("legacy path failed")

    from core.database import AsyncSessionLocal
    from sqlalchemy import text

    async with AsyncSessionLocal() as db:
        real_id = (
            await db.execute(
                text(
                    """
                    SELECT id::text FROM telegram_accounts
                    WHERE status = 'banned'
                    ORDER BY created_at
                    LIMIT 1
                    """
                )
            )
        ).scalar()
    if not real_id:
        raise SystemExit("no banned account available for enqueue probe")

    set_ownership_lookup(
        lambda account_id: AccountOwnership(
            account_id=account_id,
            owner="runtime",
            generation=1,
        )
    )
    queued = await submit_telegram_command(
        command_type="shadow_probe",
        account_id=str(real_id),
        legacy_execute=_legacy,
        idempotency_key="stage6-probe-runtime",
    )
    reset_ownership_runtime_state()
    print(
        "RUNTIME",
        queued.owner,
        queued.status,
        queued.executed,
        queued.command_id,
        queued.reason,
    )
    if not (
        (not queued.executed)
        and queued.owner == "runtime"
        and queued.status == "accepted"
        and queued.accepted_not_sent
    ):
        raise SystemExit("runtime path failed")

    from core.database import AsyncSessionLocal
    from sqlalchemy import text

    async with AsyncSessionLocal() as db:
        deleted = (
            await db.execute(
                text(
                    """
                    DELETE FROM runtime_commands
                    WHERE idempotency_key = 'stage6-probe-runtime'
                       OR (created_by = 'gateway' AND command_type = 'shadow_probe')
                    RETURNING id::text
                    """
                )
            )
        ).fetchall()
        await db.commit()
    print("CLEANED", [row[0] for row in deleted])
    print("stage6 gateway probe passed")


if __name__ == "__main__":
    asyncio.run(main())
