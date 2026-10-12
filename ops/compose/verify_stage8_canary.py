"""Stage 8 probe: canary stays disabled and never writes ownership."""

from __future__ import annotations

from services.runtime_canary import (
    ABORT_CHECKS,
    EXPAND_STEPS,
    next_expand_step,
    plan_account_switch,
    should_abort_canary,
)


def main() -> None:
    disabled = plan_account_switch({"healthy": True}, canary_enabled=False)
    if disabled.get("ok") or disabled.get("reasons") != ["canary_disabled"]:
        raise SystemExit(f"disabled canary must refuse: {disabled}")

    labels = [step["label"] for step in EXPAND_STEPS]
    if labels != [
        "1_internal",
        "3_low_traffic",
        "10_accounts",
        "5_percent",
        "20_percent",
        "50_percent",
        "100_percent",
    ]:
        raise SystemExit(f"unexpected expand order: {labels}")
    if next_expand_step(-1)["label"] != "1_internal":
        raise SystemExit("first expand step is not 1 internal account")
    if next_expand_step(6) is not None:
        raise SystemExit("expand must stop after 100 percent")

    if should_abort_canary({"auth_key_duplicated": 1}) != "AuthKeyDuplicated":
        raise SystemExit("AuthKeyDuplicated abort missing")
    if should_abort_canary({"duplicate_or_lost_messages": True}) != "message_duplicate_or_lost":
        raise SystemExit("duplicate abort missing")
    if should_abort_canary({"online_rate_drop": True}) != "online_rate_drop":
        raise SystemExit("online drop abort missing")
    if should_abort_canary({"video_failure_rate_up": True}) != "video_failure_rate_up":
        raise SystemExit("video abort missing")
    if should_abort_canary({"command_queue_backlog": True}) != "command_queue_backlog":
        raise SystemExit("backlog abort missing")
    if should_abort_canary({}) is not None:
        raise SystemExit("empty metrics must not abort")
    if set(ABORT_CHECKS) != {
        "message_duplicate_or_lost",
        "AuthKeyDuplicated",
        "online_rate_drop",
        "video_failure_rate_up",
        "command_queue_backlog",
    }:
        raise SystemExit("abort check list drifted")

    admitted = plan_account_switch(
        {
            "sending": False,
            "in_call": False,
            "pending_review": False,
            "session_complete": True,
            "healthy": True,
            "generation": 1,
        },
        canary_enabled=True,
    )
    if not admitted.get("ok") or admitted.get("next_generation") != 2:
        raise SystemExit(f"enabled healthy plan should be ok: {admitted}")
    blocked = plan_account_switch(
        {"sending": True, "healthy": True, "generation": 1},
        canary_enabled=True,
    )
    if blocked.get("ok") or "sending" not in blocked.get("reasons", []):
        raise SystemExit(f"sending account must be blocked: {blocked}")
    print("stage8 canary probe passed")


if __name__ == "__main__":
    main()
