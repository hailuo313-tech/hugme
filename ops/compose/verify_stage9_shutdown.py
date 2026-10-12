"""Stage 9 probe: default flag keeps Legacy; helper never stops it."""

from __future__ import annotations

from services.runtime_legacy_shutdown import (
    KEEP_IMAGE_DAYS,
    MIN_STABLE_HOURS,
    OBSERVE_AFTER_STOP_HOURS,
    legacy_shutdown_ready,
)


def main() -> None:
    if MIN_STABLE_HOURS != 72 or KEEP_IMAGE_DAYS != 7 or OBSERVE_AFTER_STOP_HOURS != 24:
        raise SystemExit("shutdown windows drifted")

    blocked = legacy_shutdown_ready()
    if blocked.get("ok") or "legacy_flag_enabled" not in blocked.get("reasons", []):
        raise SystemExit(f"default flag must keep legacy: {blocked}")

    current = legacy_shutdown_ready(
        legacy_enabled=True,
        runtime_stable_hours=0,
        legacy_connected_clients=360,
        legacy_incomplete_jobs=1,
        runtime_account_count=0,
        total_account_count=512,
    )
    for reason in (
        "legacy_flag_enabled",
        "runtime_not_stable_72h",
        "legacy_clients_online",
        "legacy_jobs_open",
        "not_all_accounts_on_runtime",
    ):
        if reason not in current.get("reasons", []):
            raise SystemExit(f"current production-like state missing {reason}: {current}")
    if current.get("ok"):
        raise SystemExit(f"current production-like state must not be ready: {current}")

    even_if_flag_off = legacy_shutdown_ready(
        legacy_enabled=False,
        runtime_stable_hours=10,
        legacy_connected_clients=360,
        legacy_incomplete_jobs=0,
        runtime_account_count=0,
        total_account_count=512,
    )
    if even_if_flag_off.get("ok"):
        raise SystemExit(f"360 legacy clients must block shutdown: {even_if_flag_off}")

    ready = legacy_shutdown_ready(
        legacy_enabled=False,
        runtime_stable_hours=72,
        legacy_connected_clients=0,
        legacy_incomplete_jobs=0,
        runtime_account_count=10,
        total_account_count=10,
    )
    if not ready.get("ok"):
        raise SystemExit(f"synthetic ready case failed: {ready}")
    if ready.get("keep_image_days") != 7:
        raise SystemExit(f"keep image window missing: {ready}")
    if ready.get("observe_after_stop") != "1 day, 0:00:00":
        raise SystemExit(f"observe window missing: {ready}")
    print("stage9 shutdown probe passed")


if __name__ == "__main__":
    main()
