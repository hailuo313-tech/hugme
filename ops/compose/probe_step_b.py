"""Step B probe: fake runtime account send is accepted then executed."""

from __future__ import annotations

import asyncio
import json
import time

from sqlalchemy import text

from core.database import AsyncSessionLocal
from services.runtime_ownership import reset_ownership_runtime_state
from services.telegram_command_gateway import submit_telegram_command


async def _legacy_must_not_run():
    raise RuntimeError("legacy_execute_must_not_run_for_runtime_account")


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

    command_id = None
    try:
        reset_ownership_runtime_state()
        gated = await submit_telegram_command(
            command_type="send_message",
            account_id=banned,
            legacy_execute=_legacy_must_not_run,
            payload={"runtime_probe": True, "text": "step-b-probe", "chat_id": 1},
            idempotency_key=f"step-b-probe:{int(time.time())}",
            trace_id="step-b-probe",
        )
        if not gated.accepted_not_sent:
            raise SystemExit(f"gateway must accept runtime send, got {gated}")
        command_id = gated.command_id
        if not command_id:
            raise SystemExit("gateway did not return command_id")

        deadline = time.time() + 20
        row = None
        while time.time() < deadline:
            async with AsyncSessionLocal() as db:
                row = (
                    await db.execute(
                        text(
                            """
                            SELECT status, result, error
                            FROM runtime_commands
                            WHERE id = CAST(:command_id AS uuid)
                            """
                        ),
                        {"command_id": command_id},
                    )
                ).mappings().first()
            if row and str(row["status"]) == "succeeded":
                break
            await asyncio.sleep(0.5)
        else:
            raise SystemExit(f"command not executed in time: {dict(row) if row else None}")

        result = row["result"]
        if isinstance(result, str):
            result = json.loads(result)
        if not result or result.get("executed") is not True:
            raise SystemExit(f"send must be executed=true, got {result}")
        if result.get("reason") != "runtime_probe_executed":
            raise SystemExit(f"unexpected execute reason {result}")
        print("stepB probe passed", banned, command_id)
    finally:
        async with AsyncSessionLocal() as db:
            if command_id:
                await db.execute(
                    text("DELETE FROM runtime_events WHERE command_id = CAST(:command_id AS uuid)"),
                    {"command_id": command_id},
                )
                await db.execute(
                    text("DELETE FROM runtime_commands WHERE id = CAST(:command_id AS uuid)"),
                    {"command_id": command_id},
                )
            await db.execute(
                text("DELETE FROM telegram_account_ownership WHERE account_id = CAST(:account_id AS uuid)"),
                {"account_id": banned},
            )
            leftover_own = (
                await db.execute(text("SELECT count(*)::int FROM telegram_account_ownership"))
            ).scalar()
            leftover_cmd = (
                await db.execute(
                    text(
                        "SELECT count(*)::int FROM runtime_commands WHERE idempotency_key LIKE 'step-b-probe:%'"
                    )
                )
            ).scalar()
            await db.commit()
        if leftover_own != 0:
            raise SystemExit(f"ownership table not cleaned: {leftover_own}")
        if leftover_cmd != 0:
            raise SystemExit(f"probe commands leftover: {leftover_cmd}")


if __name__ == "__main__":
    asyncio.run(main())
