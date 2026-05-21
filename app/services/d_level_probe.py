"""D-level profile completion probe trigger (P2-03)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from services.script_match_hooks import ScriptMatchContext

PROBE_SCRIPT_MATCH_STAGE = "probe"
PROBE_TRIGGER_TURN_LIMIT = 3

ProbeReason = Literal[
    "d_level_profile_incomplete",
    "not_d_level",
    "profile_complete",
    "turn_limit_exceeded",
]


@dataclass(frozen=True)
class DLevelProbeInput:
    user_id: str
    user_level: str
    profile_complete: bool
    turn_index: int
    platform: str = "telegram_real_user"
    user_text: str = ""
    missing_fields: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DLevelProbeDecision:
    should_trigger: bool
    reason: ProbeReason
    turn_index: int
    within_turn_limit: bool
    script_match_context: ScriptMatchContext | None = None


def should_trigger_d_level_probe(inp: DLevelProbeInput) -> DLevelProbeDecision:
    """Decide whether this turn should trigger profile completion probing."""
    normalized_level = str(inp.user_level).strip().upper()
    if normalized_level != "D":
        return _decision(False, "not_d_level", inp)
    if inp.profile_complete:
        return _decision(False, "profile_complete", inp)
    if inp.turn_index < 1:
        raise ValueError("turn_index must be >= 1")
    if inp.turn_index > PROBE_TRIGGER_TURN_LIMIT:
        return _decision(False, "turn_limit_exceeded", inp)
    return _decision(True, "d_level_profile_incomplete", inp)


def build_probe_script_match_context(inp: DLevelProbeInput) -> ScriptMatchContext:
    """Build the reserved ③ probe script-match contract for P3-20 wiring."""
    metadata = {
        "user_id": inp.user_id,
        "turn_index": inp.turn_index,
        "missing_fields": list(inp.missing_fields),
        "probe_trigger": "d_level_profile_completion",
        **inp.metadata,
    }
    return ScriptMatchContext(
        hook="probe",
        platform=inp.platform,
        user_level="D",
        user_text=inp.user_text,
        script_match_stage=PROBE_SCRIPT_MATCH_STAGE,
        metadata=metadata,
    )


def _decision(
    should_trigger: bool,
    reason: ProbeReason,
    inp: DLevelProbeInput,
) -> DLevelProbeDecision:
    within = 1 <= inp.turn_index <= PROBE_TRIGGER_TURN_LIMIT
    return DLevelProbeDecision(
        should_trigger=should_trigger,
        reason=reason,
        turn_index=inp.turn_index,
        within_turn_limit=within,
        script_match_context=build_probe_script_match_context(inp) if should_trigger else None,
    )
