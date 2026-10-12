"""Stage 7 helper probe: missing ownership still runs, runtime is skipped."""

from __future__ import annotations

import asyncio

from services.runtime_ownership import (
    AccountOwnership,
    fencing_allows,
    legacy_worker_should_handle,
    legacy_worker_should_handle_account,
    reset_ownership_runtime_state,
    set_ownership_lookup,
    switch_admission,
)


async def main() -> None:
    reset_ownership_runtime_state()
    missing = AccountOwnership(account_id="x", owner="legacy", generation=0)
    runtime = AccountOwnership(account_id="x", owner="runtime", generation=2)
    if not legacy_worker_should_handle(None):
        raise SystemExit("None must be handled by legacy")
    if not legacy_worker_should_handle(missing):
        raise SystemExit("missing/legacy must be handled")
    if legacy_worker_should_handle(runtime):
        raise SystemExit("runtime must be skipped")
    if not fencing_allows(0, None):
        raise SystemExit("missing generation must pass fencing")
    if fencing_allows(1, runtime):
        raise SystemExit("old generation must fail fencing")
    if not fencing_allows(2, runtime):
        raise SystemExit("current generation must pass fencing")

    admission = switch_admission(
        sending=True,
        in_call=False,
        pending_review=True,
        session_complete=True,
        healthy=True,
        generation=3,
    )
    if admission["ok"] or "sending" not in admission["reasons"] or admission["next_generation"] != 4:
        raise SystemExit("switch admission failed")

    set_ownership_lookup(lambda _account_id: None)
    if not await legacy_worker_should_handle_account("11111111-1111-1111-1111-111111111111"):
        raise SystemExit("lookup miss must be legacy")
    set_ownership_lookup(lambda account_id: AccountOwnership(account_id, "runtime", 1))
    if await legacy_worker_should_handle_account("11111111-1111-1111-1111-111111111111"):
        raise SystemExit("runtime lookup must skip")
    reset_ownership_runtime_state()
    if not await legacy_worker_should_handle_account(None):
        raise SystemExit("empty account id must be legacy")
    print("stage7 fencing probe passed")


if __name__ == "__main__":
    asyncio.run(main())
