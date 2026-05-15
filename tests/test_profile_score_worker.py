"""D4-4：profile_score_worker — initiation 映射 + min-only trigger_threshold。"""
from __future__ import annotations

import pytest

from services import profile_score_worker as psw


def test_compute_initiation_score_from_count_saturates():
    assert psw.compute_initiation_score_from_count(0, cap_messages=40) == 0.0
    assert psw.compute_initiation_score_from_count(20, cap_messages=40) == 50.0
    assert psw.compute_initiation_score_from_count(40, cap_messages=40) == 100.0
    assert psw.compute_initiation_score_from_count(999, cap_messages=40) == 100.0


def test_min_score_for_trigger_threshold_respects_zero_dims():
    # 仅 loneliness；initiation=0 不参与
    assert psw.min_score_for_trigger_threshold(0, 0, 0, 0, 35.0) == 35.0
    # initiation 参与
    assert psw.min_score_for_trigger_threshold(50, 0, 0, 0, 60.0) == 50.0
    # emotion>0 参与
    assert psw.min_score_for_trigger_threshold(0, 20, 0, 0, 35.0) == 20.0


def test_trigger_threshold_cold_start_matches_sql_default():
    """m≈35（仅孤独度冷启动）→ threshold≈65，与 init.sql DEFAULT 65 一致。"""
    tt = psw.compute_trigger_threshold_min_only(
        0, 0, 0, 0, 35.0,
        base=65.0, pivot=35.0, k=0.15, floor=50.0, ceil=82.0,
    )
    assert tt == 65.0


def test_trigger_threshold_not_always_default_when_loneliness_rises():
    tt = psw.compute_trigger_threshold_min_only(
        0, 0, 0, 0, 60.0,
        base=65.0, pivot=35.0, k=0.15, floor=50.0, ceil=82.0,
    )
    assert tt != 65.0
    assert 50.0 <= tt <= 82.0
    assert tt == pytest.approx(61.25)


def test_trigger_threshold_with_initiation_in_min_pool():
    tt = psw.compute_trigger_threshold_min_only(
        80.0, 0, 0, 0, 50.0,
        base=65.0, pivot=35.0, k=0.15, floor=50.0, ceil=82.0,
    )
    assert psw.min_score_for_trigger_threshold(80, 0, 0, 0, 50) == 50.0
    assert tt == pytest.approx(62.75)


def test_profile_score_scheduler_respects_disabled(monkeypatch):
    import importlib

    from core import config

    monkeypatch.setattr(config.settings, "SCORE_WORKER_ENABLED", False)
    pss = importlib.reload(importlib.import_module("services.profile_score_scheduler"))
    pss.shutdown_scheduler()
    assert pss.start_scheduler() is None
