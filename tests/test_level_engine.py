"""C-05 / P2-08: level_engine boundary cases (>=20) and branch coverage."""

from __future__ import annotations

import pytest

from services.level_engine import (
    CHAT_ROUTE_BY_LEVEL,
    LevelThresholds,
    UserLevelInput,
    calc_user_level,
    country_tier,
    level_to_chat_route,
    load_t1_countries,
    load_thresholds,
)

T1 = frozenset({"US", "SG"})
T2 = frozenset({"BR", "IN"})


@pytest.fixture
def th() -> LevelThresholds:
    return LevelThresholds(
        s_min_spend=500.0,
        a_min_spend=99.0,
        b_min_spend=0.0,
        vip_level_a_min=1,
        tier_default_level={"T1": "B", "T2": "C", "T3": "C", "unknown": "C"},
    )


# --- country_tier (cases 1-6) ---


@pytest.mark.parametrize(
    "code,expected",
    [
        ("US", "T1"),
        ("us", "T1"),
        ("BR", "T2"),
        ("ZZ", "T3"),
        ("", "unknown"),
        (None, "unknown"),
    ],
    ids=["t1-us", "t1-lower", "t2-br", "t3-other", "empty", "none"],
)
def test_country_tier_mapping(code, expected):
    assert country_tier(code, t1=T1, t2=T2) == expected


# --- level_to_chat_route (cases 7-11) ---


@pytest.mark.parametrize(
    "level,route",
    [
        ("S", "manual_premium"),
        ("A", "manual_premium"),
        ("B", "ai_assisted"),
        ("C", "ai_auto"),
        ("D", "ai_auto"),
    ],
)
def test_level_to_chat_route(level, route):
    assert level_to_chat_route(level) == route


def test_chat_route_mapping_is_complete_and_explicit():
    assert CHAT_ROUTE_BY_LEVEL == {
        "S": "manual_premium",
        "A": "manual_premium",
        "B": "ai_assisted",
        "C": "ai_auto",
        "D": "ai_auto",
    }


# --- calc_user_level core (cases 12-25+) ---


def test_incomplete_profile_forces_d(th):
    r = calc_user_level(
        UserLevelInput(profile_complete=False, country_code="US", lifetime_spend_usd=9999),
        th,
        t1=T1,
        t2=T2,
    )
    assert r.level == "D"
    assert r.reason == "profile_incomplete_probe"


def test_operator_assigned_s(th):
    r = calc_user_level(
        UserLevelInput(profile_complete=True, operator_assigned_s=True, country_code="US"),
        th,
        t1=T1,
        t2=T2,
    )
    assert r.level == "S"
    assert r.reason == "operator_assigned_s"


def test_t1_high_spend_s(th):
    r = calc_user_level(
        UserLevelInput(profile_complete=True, country_code="US", lifetime_spend_usd=500),
        th,
        t1=T1,
        t2=T2,
    )
    assert r.level == "S"


def test_t1_spend_just_below_s_threshold_is_not_s(th):
    r = calc_user_level(
        UserLevelInput(profile_complete=True, country_code="US", lifetime_spend_usd=499.99),
        th,
        t1=T1,
        t2=T2,
    )
    assert r.level == "A"


def test_spend_at_a_threshold(th):
    r = calc_user_level(
        UserLevelInput(profile_complete=True, country_code="IN", lifetime_spend_usd=99),
        th,
        t1=T1,
        t2=T2,
    )
    assert r.level == "A"
    assert r.reason == "spend_or_vip_a"


def test_spend_just_below_a_threshold_t2_default_c(th):
    r = calc_user_level(
        UserLevelInput(profile_complete=True, country_code="IN", lifetime_spend_usd=98.99),
        th,
        t1=T1,
        t2=T2,
    )
    assert r.level == "C"


def test_vip_without_spend_a(th):
    r = calc_user_level(
        UserLevelInput(profile_complete=True, country_code="IN", vip_level=1),
        th,
        t1=T1,
        t2=T2,
    )
    assert r.level == "A"


def test_t1_zero_spend_b(th):
    r = calc_user_level(
        UserLevelInput(profile_complete=True, country_code="US", lifetime_spend_usd=0),
        th,
        t1=T1,
        t2=T2,
    )
    assert r.level == "B"
    assert r.reason == "t1_default_b"


def test_unknown_country_default_c(th):
    r = calc_user_level(
        UserLevelInput(profile_complete=True, country_code=None),
        th,
        t1=T1,
        t2=T2,
    )
    assert r.level == "C"
    assert r.country_tier == "unknown"


def test_t3_country_default_c(th):
    r = calc_user_level(
        UserLevelInput(profile_complete=True, country_code="ZZ"),
        th,
        t1=T1,
        t2=T2,
    )
    assert r.level == "C"
    assert r.country_tier == "T3"


def test_negative_spend_treated_as_zero(th):
    r = calc_user_level(
        UserLevelInput(profile_complete=True, country_code="US", lifetime_spend_usd=-10),
        th,
        t1=T1,
        t2=T2,
    )
    assert r.level == "B"


def test_config_files_load():
    t1 = load_t1_countries()
    assert "US" in t1
    th = load_thresholds()
    assert th.a_min_spend >= 0


def test_high_spend_non_t1_does_not_auto_s(th):
    r = calc_user_level(
        UserLevelInput(profile_complete=True, country_code="BR", lifetime_spend_usd=1000),
        th,
        t1=T1,
        t2=T2,
    )
    assert r.level == "A"


def test_result_always_has_chat_route(th):
    r = calc_user_level(UserLevelInput(profile_complete=True, country_code="US"), th, t1=T1, t2=T2)
    assert r.chat_route in {"manual_premium", "ai_assisted", "ai_auto"}
