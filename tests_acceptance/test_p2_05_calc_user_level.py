"""P2-05: calc_user_level pure function returns S/A/B/C/D correctly."""
from __future__ import annotations

from services.level_engine import (
    LevelThresholds,
    UserLevelInput,
    calc_user_level,
)

T1 = frozenset({"US", "SG"})
T2 = frozenset({"BR", "IN"})


def _thresholds() -> LevelThresholds:
    return LevelThresholds(
        s_min_spend=200.0,
        a_min_spend=99.0,
        b_min_spend=0.0,
        vip_level_a_min=1,
        tier_default_level={"T1": "B", "T2": "C", "T3": "C", "unknown": "C"},
    )


def test_t1_spend_at_200_returns_s():
    result = calc_user_level(
        UserLevelInput(
            profile_complete=True,
            country_code="US",
            lifetime_spend_usd=200,
        ),
        _thresholds(),
        t1=T1,
        t2=T2,
    )

    assert result.level == "S"
    assert result.reason == "t1_high_spend"
    assert result.chat_route == "manual_premium"


def test_spend_at_99_returns_a_even_for_non_t1():
    result = calc_user_level(
        UserLevelInput(
            profile_complete=True,
            country_code="BR",
            lifetime_spend_usd=99,
        ),
        _thresholds(),
        t1=T1,
        t2=T2,
    )

    assert result.level == "A"
    assert result.reason == "spend_or_vip_a"
    assert result.chat_route == "manual_premium"


def test_vip_level_one_returns_a_without_spend():
    result = calc_user_level(
        UserLevelInput(
            profile_complete=True,
            country_code="ZZ",
            vip_level=1,
        ),
        _thresholds(),
        t1=T1,
        t2=T2,
    )

    assert result.level == "A"
    assert result.reason == "spend_or_vip_a"


def test_complete_t1_below_a_threshold_defaults_to_b():
    result = calc_user_level(
        UserLevelInput(
            profile_complete=True,
            country_code="SG",
            lifetime_spend_usd=98.99,
        ),
        _thresholds(),
        t1=T1,
        t2=T2,
    )

    assert result.level == "B"
    assert result.reason == "t1_default_b"
    assert result.chat_route == "ai_assisted"


def test_complete_t2_below_a_threshold_defaults_to_c():
    result = calc_user_level(
        UserLevelInput(
            profile_complete=True,
            country_code="IN",
            lifetime_spend_usd=0,
        ),
        _thresholds(),
        t1=T1,
        t2=T2,
    )

    assert result.level == "C"
    assert result.reason == "tier_default_t2"
    assert result.chat_route == "ai_auto"


def test_incomplete_profile_returns_d_before_spend_rules():
    result = calc_user_level(
        UserLevelInput(
            profile_complete=False,
            country_code="US",
            lifetime_spend_usd=999,
            vip_level=9,
        ),
        _thresholds(),
        t1=T1,
        t2=T2,
    )

    assert result.level == "D"
    assert result.reason == "profile_incomplete_probe"
    assert result.chat_route == "ai_auto"
