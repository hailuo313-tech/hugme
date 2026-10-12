from __future__ import annotations

import pytest

from services.d_level_probe import (
    PROBE_SCRIPT_MATCH_STAGE,
    PROBE_TRIGGER_TURN_LIMIT,
    DLevelProbeInput,
    build_probe_script_match_context,
    should_trigger_d_level_probe,
)
from services.script_match_hooks import evaluate_script_hook


@pytest.mark.parametrize("turn_index", [1, 2, 3])
def test_d_level_incomplete_profile_triggers_within_three_turns(turn_index: int) -> None:
    decision = should_trigger_d_level_probe(
        DLevelProbeInput(
            user_id="u1",
            user_level="D",
            profile_complete=False,
            turn_index=turn_index,
            user_text="hello",
            missing_fields=("age", "country_code"),
        )
    )

    assert decision.should_trigger is True
    assert decision.reason == "d_level_profile_incomplete"
    assert decision.within_turn_limit is True
    assert decision.script_match_context is not None
    assert decision.script_match_context.hook == "probe"
    assert decision.script_match_context.script_match_stage == PROBE_SCRIPT_MATCH_STAGE
    assert decision.script_match_context.metadata["missing_fields"] == ["age", "country_code"]


def test_probe_script_match_context_uses_reserved_probe_hook() -> None:
    ctx = build_probe_script_match_context(
        DLevelProbeInput(
            user_id="u1",
            user_level="D",
            profile_complete=False,
            turn_index=1,
            platform="telegram_real_user",
            user_text="hi",
        )
    )
    result = evaluate_script_hook(ctx)

    assert ctx.hook == "probe"
    assert ctx.script_match_stage == "probe"
    assert ctx.metadata["probe_trigger"] == "d_level_profile_completion"
    assert result.hook == "probe"
    assert result.degradation == "p3_20_retrieval_not_wired"


def test_non_d_level_does_not_trigger() -> None:
    decision = should_trigger_d_level_probe(
        DLevelProbeInput(user_id="u1", user_level="C", profile_complete=False, turn_index=1)
    )

    assert decision.should_trigger is False
    assert decision.reason == "not_d_level"
    assert decision.script_match_context is None


def test_complete_profile_does_not_trigger_even_for_d_level() -> None:
    decision = should_trigger_d_level_probe(
        DLevelProbeInput(user_id="u1", user_level="D", profile_complete=True, turn_index=1)
    )

    assert decision.should_trigger is False
    assert decision.reason == "profile_complete"


def test_after_three_turns_reports_sla_miss_without_triggering() -> None:
    decision = should_trigger_d_level_probe(
        DLevelProbeInput(
            user_id="u1",
            user_level="D",
            profile_complete=False,
            turn_index=PROBE_TRIGGER_TURN_LIMIT + 1,
        )
    )

    assert decision.should_trigger is False
    assert decision.reason == "turn_limit_exceeded"
    assert decision.within_turn_limit is False


def test_turn_index_must_be_positive() -> None:
    with pytest.raises(ValueError):
        should_trigger_d_level_probe(
            DLevelProbeInput(user_id="u1", user_level="D", profile_complete=False, turn_index=0)
        )
