"""Step A probe: all-role process must not connect a runtime-owned account."""

from __future__ import annotations

import asyncio

from services.runtime_ownership import (
    get_account_ownership,
    reset_ownership_runtime_state,
    this_process_may_hold_telegram_session,
)
from services.telegram_account_manager import telegram_account_manager


async def main() -> None:
    reset_ownership_runtime_state()
    missing = await this_process_may_hold_telegram_session(None)
    if not missing:
        raise SystemExit("missing ownership must stay holdable on all")
    fake = "00000000-0000-4000-8000-000000000001"
    reset_ownership_runtime_state()
    if not await this_process_may_hold_telegram_session(fake):
        raise SystemExit("unknown uuid without row must stay legacy/holdable")
    print("stepA helper defaults passed")


if __name__ == "__main__":
    asyncio.run(main())
