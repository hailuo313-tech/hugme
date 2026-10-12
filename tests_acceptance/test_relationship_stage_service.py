"""REL-01: relationship_stage auto-adjustment service."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.relationship_stage_service import (
    maybe_auto_adjust_relationship_stage,
    normalize_relationship_stage,
    resolve_relationship_stage,
)


def _patch_rel_settings():
    return patch("services.relationship_stage_service.settings")


def _apply_default_rel_settings(settings_mock):
    settings_mock.REL_STAGE_AUTO_ENABLED = True
    settings_mock.REL_STAGE_ALLOW_DOWNGRADE = True
    settings_mock.REL_STAGE_INITIATION_S1 = 10.0
    settings_mock.REL_STAGE_INITIATION_S2 = 30.0
    settings_mock.REL_STAGE_INITIATION_S3 = 55.0
    settings_mock.REL_STAGE_INITIATION_S4 = 78.0
    settings_mock.REL_STAGE_VIP_MIN_FOR_S1 = 1


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "S0"),
        ("s2", "S2"),
        (" S4 ", "S4"),
        ("bad", "S0"),
    ],
)
def test_normalize_relationship_stage(value, expected):
    assert normalize_relationship_stage(value) == expected


@pytest.mark.parametrize(
    "score,expected",
    [
        (0, "S0"),
        (10, "S1"),
        (30, "S2"),
        (55, "S3"),
        (78, "S4"),
        (100, "S4"),
    ],
)
def test_resolve_relationship_stage_by_initiation_score(score, expected):
    with _patch_rel_settings() as settings_mock:
        _apply_default_rel_settings(settings_mock)
        decision = resolve_relationship_stage(
            {"relationship_stage": "S0", "initiation_score": score, "vip_level": 0}
        )

    assert decision.target_stage == expected
    assert decision.changed is (expected != "S0")


def test_vip_profile_has_s1_floor():
    with _patch_rel_settings() as settings_mock:
        _apply_default_rel_settings(settings_mock)
        decision = resolve_relationship_stage(
            {"relationship_stage": "S0", "initiation_score": 0, "vip_level": 1}
        )

    assert decision.target_stage == "S1"
    assert decision.reason == "vip_floor"


def test_s5_is_locked_out_of_auto_adjustment():
    with _patch_rel_settings() as settings_mock:
        _apply_default_rel_settings(settings_mock)
        decision = resolve_relationship_stage(
            {"relationship_stage": "S5", "initiation_score": 100, "vip_level": 9}
        )

    assert decision.target_stage == "S5"
    assert decision.changed is False
    assert decision.reason == "s5_locked"


def test_downgrade_can_be_disabled():
    with _patch_rel_settings() as settings_mock:
        _apply_default_rel_settings(settings_mock)
        decision = resolve_relationship_stage(
            {"relationship_stage": "S3", "initiation_score": 0, "vip_level": 0},
            allow_downgrade=False,
        )

    assert decision.target_stage == "S3"
    assert decision.changed is False
    assert decision.reason == "downgrade_disabled"


@pytest.mark.asyncio
async def test_maybe_auto_adjust_updates_db_and_profile_row():
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    profile = {"relationship_stage": "S1", "initiation_score": 60, "vip_level": 0}

    with _patch_rel_settings() as settings_mock:
        _apply_default_rel_settings(settings_mock)
        out = await maybe_auto_adjust_relationship_stage(
            db,
            user_id="00000000-0000-0000-0000-000000000001",
            profile_row=profile,
            trace_id="tr",
        )

    assert out == "S3"
    assert profile["relationship_stage"] == "S3"
    db.execute.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_maybe_auto_adjust_noop_when_disabled():
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()

    with _patch_rel_settings() as settings_mock:
        _apply_default_rel_settings(settings_mock)
        settings_mock.REL_STAGE_AUTO_ENABLED = False
        out = await maybe_auto_adjust_relationship_stage(
            db,
            user_id="u1",
            profile_row={"relationship_stage": "S0", "initiation_score": 100},
            trace_id="tr",
        )

    assert out is None
    db.execute.assert_not_called()
    db.commit.assert_not_called()
