from __future__ import annotations

from pathlib import Path

from services.canary_feature_flags import decide_level_canary, load_policy


ROOT = Path(__file__).resolve().parents[1]
H07 = ROOT / "config" / "h07_week9_cd_canary_approval.json"
H08 = ROOT / "config" / "h08_week10_11_bas_approval.json"


def test_p5_09_h07_enables_only_cd_auto_cutover() -> None:
    policy = load_policy(H07)

    assert decide_level_canary(level="C", user_id="u-c", policy=policy).enabled is True
    assert decide_level_canary(level="D", user_id="u-d", policy=policy).enabled is True

    for level in ["S", "A", "B"]:
        decision = decide_level_canary(level=level, user_id=f"u-{level}", policy=policy)
        assert decision.enabled is False
        assert decision.reason == "level_not_enabled"


def test_p5_09_h08_preserves_routes_by_level() -> None:
    policy = load_policy(H08)

    expected = {
        "S": "manual_premium",
        "A": "manual_premium",
        "B": "ai_assisted",
        "C": "ai_auto",
        "D": "ai_auto",
    }
    for level, route in expected.items():
        decision = decide_level_canary(level=level, user_id=f"u-{level}", policy=policy)
        assert decision.enabled is True
        assert decision.chat_route == route
        assert decision.traffic_percent == 100


def test_p5_09_global_flag_can_disable_all_levels() -> None:
    policy = load_policy(H08)

    decision = decide_level_canary(
        level="C",
        user_id="u-c",
        policy=policy,
        feature_enabled=False,
    )

    assert decision.enabled is False
    assert decision.reason == "feature_disabled"
