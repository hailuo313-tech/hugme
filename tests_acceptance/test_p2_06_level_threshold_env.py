"""P2-06: level thresholds can be overridden by environment configuration."""
from __future__ import annotations

import json
from pathlib import Path

from services.level_engine import UserLevelInput, calc_user_level, load_thresholds


def _write_thresholds(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "spend_usd": {"s_min": 200, "a_min": 99, "b_min": 0},
                "vip_level_a_min": 1,
                "tier_default_level": {
                    "T1": "B",
                    "T2": "C",
                    "T3": "C",
                    "unknown": "C",
                },
            }
        ),
        encoding="utf-8",
    )


def test_env_file_overrides_spend_thresholds(tmp_path: Path):
    config_path = tmp_path / "level_thresholds.json"
    env_path = tmp_path / ".env"
    _write_thresholds(config_path)
    env_path.write_text(
        "\n".join(
            [
                "LEVEL_S_MIN_SPEND=150",
                "LEVEL_A_MIN_SPEND=80",
                "LEVEL_B_MIN_SPEND=10",
                "LEVEL_VIP_LEVEL_A_MIN=2",
            ]
        ),
        encoding="utf-8",
    )

    thresholds = load_thresholds(config_path, env_path=env_path)

    assert thresholds.s_min_spend == 150
    assert thresholds.a_min_spend == 80
    assert thresholds.b_min_spend == 10
    assert thresholds.vip_level_a_min == 2


def test_environment_variables_take_priority_over_env_file(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "level_thresholds.json"
    env_path = tmp_path / ".env"
    _write_thresholds(config_path)
    env_path.write_text("LEVEL_A_MIN_SPEND=80\n", encoding="utf-8")
    monkeypatch.setenv("LEVEL_A_MIN_SPEND", "120")

    thresholds = load_thresholds(config_path, env_path=env_path)

    assert thresholds.a_min_spend == 120


def test_env_threshold_change_affects_calc_user_level(tmp_path: Path):
    config_path = tmp_path / "level_thresholds.json"
    env_path = tmp_path / ".env"
    _write_thresholds(config_path)
    env_path.write_text("LEVEL_A_MIN_SPEND=120\n", encoding="utf-8")
    thresholds = load_thresholds(config_path, env_path=env_path)

    result = calc_user_level(
        UserLevelInput(
            profile_complete=True,
            country_code="BR",
            lifetime_spend_usd=100,
        ),
        thresholds,
        t1=frozenset({"US"}),
        t2=frozenset({"BR"}),
    )

    assert result.level == "C"
    assert result.reason == "tier_default_t2"


def test_env_file_can_override_default_level_mapping(tmp_path: Path):
    config_path = tmp_path / "level_thresholds.json"
    env_path = tmp_path / ".env"
    _write_thresholds(config_path)
    env_path.write_text("LEVEL_T2_DEFAULT=B\n", encoding="utf-8")

    thresholds = load_thresholds(config_path, env_path=env_path)

    assert thresholds.tier_default_level["T2"] == "B"
