"""After Step A restore: a banned account marked runtime must not be connected."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from core.database import AsyncSessionLocal
from services.runtime_ownership import (
    reset_ownership_runtime_state,
    this_process_may_hold_telegram_session,
)
from services.telegram_account_manager import telegram_account_manager


async def main() -> None:
    async with AsyncSessionLocal() as db:
        banned = (
            await db.execute(
                text(
                    """
                    SELECT id::text FROM telegram_accounts
                    WHERE status = 'banned'
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                )
            )
        ).scalar()
        if not banned:
            raise SystemExit("no banned account for probe")
        await db.execute(
            text(
                """
                INSERT INTO telegram_account_ownership (account_id, owner, generation, switch_status)
                VALUES (CAST(:account_id AS uuid), 'runtime', 2, 'stable')
                ON CONFLICT (account_id) DO UPDATE
                SET owner = 'runtime', generation = 2, switch_status = 'stable', updated_at = NOW()
                """
            ),
            {"account_id": banned},
        )
        await db.commit()

    reset_ownership_runtime_state()
    may_hold = await this_process_may_hold_telegram_session(banned)
    connected = await telegram_account_manager.connect_account(
        __import__("uuid").UUID(banned)
    )
    client = await telegram_account_manager.get_client(__import__("uuid").UUID(banned))

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM telegram_account_ownership WHERE account_id = CAST(:account_id AS uuid)"),
            {"account_id": banned},
        )
        leftover = (
            await db.execute(text("SELECT count(*)::int FROM telegram_account_ownership"))
        ).scalar()
        await db.commit()

    if may_hold:
        raise SystemExit(f"all-role process must not hold runtime account {banned}")
    if connected:
        raise SystemExit(f"connect_account must refuse runtime account {banned}")
    if client is not None and getattr(client, "is_connected", lambda: False)():
        raise SystemExit(f"runtime probe account became connected {banned}")
    if leftover != 0:
        raise SystemExit(f"ownership table not cleaned: {leftover}")
    print("stepA probe passed", banned)


if __name__ == "__main__":
    asyncio.run(main())
