"""Stage 9 legacy Telegram runtime shutdown gates.

Default keeps legacy running. Shutdown is allowed only after every account has
been on the new runtime long enough and legacy has no live clients or work.
"""

from __future__ import annotations

from datetime import timedelta

MIN_STABLE_HOURS = 72
KEEP_IMAGE_DAYS = 7
OBSERVE_AFTER_STOP_HOURS = 24


def legacy_shutdown_ready(
    *,
    legacy_enabled: bool = True,
    runtime_stable_hours: float = 0,
    legacy_connected_clients: int = 0,
    legacy_incomplete_jobs: int = 0,
    runtime_account_count: int = 0,
    total_account_count: int = 0,
) -> dict:
    reasons: list[str] = []
    if legacy_enabled:
        reasons.append("legacy_flag_enabled")
    if runtime_stable_hours < MIN_STABLE_HOURS:
        reasons.append("runtime_not_stable_72h")
    if legacy_connected_clients > 0:
        reasons.append("legacy_clients_online")
    if legacy_incomplete_jobs > 0:
        reasons.append("legacy_jobs_open")
    if total_account_count and runtime_account_count < total_account_count:
        reasons.append("not_all_accounts_on_runtime")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "keep_image_days": KEEP_IMAGE_DAYS,
        "observe_after_stop": str(timedelta(hours=OBSERVE_AFTER_STOP_HOURS)),
    }
