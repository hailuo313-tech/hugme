"""Stage 8 canary helpers. Disabled until an operator explicitly starts a switch."""

from __future__ import annotations

from services.runtime_ownership import switch_admission

EXPAND_STEPS = (
    {"label": "1_internal", "count": 1, "ratio": None},
    {"label": "3_low_traffic", "count": 3, "ratio": None},
    {"label": "10_accounts", "count": 10, "ratio": None},
    {"label": "5_percent", "count": None, "ratio": 0.05},
    {"label": "20_percent", "count": None, "ratio": 0.20},
    {"label": "50_percent", "count": None, "ratio": 0.50},
    {"label": "100_percent", "count": None, "ratio": 1.00},
)

ABORT_CHECKS = (
    "message_duplicate_or_lost",
    "AuthKeyDuplicated",
    "online_rate_drop",
    "video_failure_rate_up",
    "command_queue_backlog",
)


def next_expand_step(current_index: int = -1) -> dict | None:
    nxt = current_index + 1
    if nxt < 0 or nxt >= len(EXPAND_STEPS):
        return None
    return {"index": nxt, **EXPAND_STEPS[nxt]}


def should_abort_canary(metrics: dict | None) -> str | None:
    data = metrics or {}
    if data.get("duplicate_or_lost_messages"):
        return "message_duplicate_or_lost"
    if int(data.get("auth_key_duplicated") or 0) > 0:
        return "AuthKeyDuplicated"
    if data.get("online_rate_drop"):
        return "online_rate_drop"
    if data.get("video_failure_rate_up"):
        return "video_failure_rate_up"
    if data.get("command_queue_backlog"):
        return "command_queue_backlog"
    return None


def plan_account_switch(probes: dict, *, canary_enabled: bool = False) -> dict:
    if not canary_enabled:
        return {"ok": False, "reasons": ["canary_disabled"], "next_generation": None}
    admission = switch_admission(
        sending=bool(probes.get("sending")),
        in_call=bool(probes.get("in_call")),
        pending_review=bool(probes.get("pending_review")),
        session_complete=bool(probes.get("session_complete", True)),
        healthy=bool(probes.get("healthy", True)),
        generation=int(probes.get("generation") or 1),
    )
    abort = should_abort_canary(probes.get("metrics"))
    if abort:
        admission = {**admission, "ok": False, "reasons": [*admission["reasons"], abort]}
    return admission
