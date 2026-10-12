"""D4-3 / D4-4：``loneliness_updater`` 记忆标签 + 当前句关键词。"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import loneliness_updater as lu


def test_compute_decay_when_no_tags():
    new, meta = lu.compute_next_loneliness(
        50.0,
        [[], []],
        baseline=35.0,
        per_memory_clamp=12.0,
        global_clamp=20.0,
        decay_factor=0.08,
    )
    # (35-50)*0.08 = -1.2
    assert meta["had_nonempty_tags"] is False
    assert meta["had_memory_nonempty"] is False
    assert meta["had_utterance_signal"] is False
    assert meta["delta_tags"] == 0.0
    assert meta["delta_utterance"] == 0.0
    assert pytest.approx(meta["applied_decay"], rel=1e-5) == -1.2
    assert new == pytest.approx(48.8, rel=1e-5)


def test_compute_lonely_tag_raises_score():
    new, meta = lu.compute_next_loneliness(
        35.0,
        [["lonely"]],
        baseline=35.0,
        per_memory_clamp=12.0,
        global_clamp=20.0,
        decay_factor=0.08,
    )
    assert meta["had_nonempty_tags"] is True
    assert meta["had_memory_nonempty"] is True
    assert meta["delta_utterance"] == 0.0
    assert meta["delta_tags"] == 10.0
    assert meta["applied_decay"] == 0.0
    assert new == 45.0


def test_compute_per_memory_clamp():
    new, meta = lu.compute_next_loneliness(
        40.0,
        [["lonely", "sad", "anxious"]],  # 10+8+9=27 -> clamp 12
        baseline=35.0,
        per_memory_clamp=12.0,
        global_clamp=20.0,
        decay_factor=0.08,
    )
    assert meta["delta_tags"] == 12.0
    assert new == 52.0


def test_compute_global_clamp():
    rows = [["lonely"]] * 5  # 5*10=50 -> global clamp 20
    new, meta = lu.compute_next_loneliness(
        30.0,
        rows,
        baseline=35.0,
        per_memory_clamp=12.0,
        global_clamp=20.0,
        decay_factor=0.08,
    )
    assert meta["delta_tags"] == 20.0
    assert new == 50.0


def test_compute_happy_reduces():
    new, meta = lu.compute_next_loneliness(
        60.0,
        [["happy", "calm"]],  # -8-6=-14
        baseline=35.0,
        per_memory_clamp=12.0,
        global_clamp=20.0,
        decay_factor=0.08,
    )
    assert meta["delta_tags"] == -14.0
    assert new == 46.0


def test_infer_utterance_chinese_lonely():
    tags = lu.infer_utterance_emotion_tags("最近一个人好孤独")
    assert "lonely" in tags


def test_infer_utterance_max_three_distinct():
    t = lu.infer_utterance_emotion_tags("又焦虑又难过但也很开心期待明天")
    assert len(t) <= 3
    assert len(set(t)) == len(t)


def test_compute_utterance_only_skips_decay():
    new, meta = lu.compute_next_loneliness(
        50.0,
        [],
        utterance_tags=["lonely"],
        utterance_max_delta=10.0,
        baseline=35.0,
        per_memory_clamp=12.0,
        global_clamp=20.0,
        decay_factor=0.08,
    )
    assert meta["had_memory_nonempty"] is False
    assert meta["had_utterance_signal"] is True
    assert meta["applied_decay"] == 0.0
    assert meta["delta_utterance"] == 10.0
    assert new == 60.0


def test_compute_utterance_clamped_separately_from_memory():
    new, meta = lu.compute_next_loneliness(
        40.0,
        [["lonely"]],  # +10 memory
        utterance_tags=["lonely"],  # +10 utterance, clamped to 10 total utterance
        utterance_max_delta=10.0,
        baseline=35.0,
        per_memory_clamp=12.0,
        global_clamp=20.0,
        decay_factor=0.08,
    )
    assert meta["delta_tags"] == 10.0
    assert meta["delta_utterance"] == 10.0
    assert new == 60.0


def test_infer_utterance_english_anxious():
    tags = lu.infer_utterance_emotion_tags("I feel so anxious today")
    assert "anxious" in tags


def test_infer_utterance_spanish_sad():
    tags = lu.infer_utterance_emotion_tags("Estoy muy triste hoy")
    assert "sad" in tags


@pytest.mark.asyncio
async def test_refresh_utterance_disabled_still_applies_memory_decay(monkeypatch):
    """关掉 D4-4 时 user_text 不参与；无记忆 tag 时仍走基准衰减。"""
    monkeypatch.setattr(lu.settings, "LONELINESS_REFRESH_ENABLED", True)
    monkeypatch.setattr(lu.settings, "LONELINESS_LOOKBACK_DAYS", 30)
    monkeypatch.setattr(lu.settings, "LONELINESS_MEMORY_CAP", 40)
    monkeypatch.setattr(lu.settings, "LONELINESS_PER_MEMORY_CLAMP", 12.0)
    monkeypatch.setattr(lu.settings, "LONELINESS_GLOBAL_DELTA_CLAMP", 20.0)
    monkeypatch.setattr(lu.settings, "LONELINESS_DECAY_FACTOR", 0.08)
    monkeypatch.setattr(lu.settings, "LONELINESS_BASELINE", 35.0)
    monkeypatch.setattr(lu.settings, "LONELINESS_MIN_UPDATE_DELTA", 0.05)
    monkeypatch.setattr(lu.settings, "LONELINESS_UTTERANCE_ENABLED", False)

    sel = MagicMock()
    sel.fetchall.return_value = []
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[sel, MagicMock()])
    log = MagicMock()
    log.bind = MagicMock(return_value=log)

    prof = {"loneliness_score": 50.0}
    out = await lu.refresh_loneliness_score(
        db=db,
        user_id="00000000-0000-0000-0000-000000000099",
        profile_row=prof,
        trace_id="tr",
        log=log,
        user_text="我今天特别孤独",
    )
    assert out["loneliness_score"] == pytest.approx(48.8, rel=1e-5)
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_refresh_skips_when_disabled(monkeypatch):
    monkeypatch.setattr(lu.settings, "LONELINESS_REFRESH_ENABLED", False)
    db = MagicMock()
    log = MagicMock()
    log.bind = MagicMock(return_value=log)
    prof = {"loneliness_score": 40.0, "user_id": "x"}
    out = await lu.refresh_loneliness_score(
        db=db, user_id="u", profile_row=prof, trace_id="t", log=log
    )
    assert out is prof
    db.execute.assert_not_called()


class _MemRow:
    def __init__(self, tags: list[str]):
        self._mapping: dict[str, Any] = {"emotion_tags": tags}


@pytest.mark.asyncio
async def test_refresh_updates_when_delta_large(monkeypatch):
    monkeypatch.setattr(lu.settings, "LONELINESS_REFRESH_ENABLED", True)
    monkeypatch.setattr(lu.settings, "LONELINESS_LOOKBACK_DAYS", 30)
    monkeypatch.setattr(lu.settings, "LONELINESS_MEMORY_CAP", 40)
    monkeypatch.setattr(lu.settings, "LONELINESS_PER_MEMORY_CLAMP", 12.0)
    monkeypatch.setattr(lu.settings, "LONELINESS_GLOBAL_DELTA_CLAMP", 20.0)
    monkeypatch.setattr(lu.settings, "LONELINESS_DECAY_FACTOR", 0.08)
    monkeypatch.setattr(lu.settings, "LONELINESS_BASELINE", 35.0)
    monkeypatch.setattr(lu.settings, "LONELINESS_MIN_UPDATE_DELTA", 0.05)
    monkeypatch.setattr(lu.settings, "LONELINESS_UTTERANCE_ENABLED", False)

    sel = MagicMock()
    sel.fetchall.return_value = [_MemRow(["lonely"])]
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[sel, MagicMock()])

    log = MagicMock()
    log.bind = MagicMock(return_value=log)

    prof = {"loneliness_score": 35.0}
    out = await lu.refresh_loneliness_score(
        db=db,
        user_id="00000000-0000-0000-0000-000000000099",
        profile_row=prof,
        trace_id="tr",
        log=log,
    )
    assert out["loneliness_score"] == 45.0
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_refresh_utterance_when_no_memories(monkeypatch):
    monkeypatch.setattr(lu.settings, "LONELINESS_REFRESH_ENABLED", True)
    monkeypatch.setattr(lu.settings, "LONELINESS_LOOKBACK_DAYS", 30)
    monkeypatch.setattr(lu.settings, "LONELINESS_MEMORY_CAP", 40)
    monkeypatch.setattr(lu.settings, "LONELINESS_PER_MEMORY_CLAMP", 12.0)
    monkeypatch.setattr(lu.settings, "LONELINESS_GLOBAL_DELTA_CLAMP", 20.0)
    monkeypatch.setattr(lu.settings, "LONELINESS_DECAY_FACTOR", 0.08)
    monkeypatch.setattr(lu.settings, "LONELINESS_BASELINE", 35.0)
    monkeypatch.setattr(lu.settings, "LONELINESS_MIN_UPDATE_DELTA", 0.05)
    monkeypatch.setattr(lu.settings, "LONELINESS_UTTERANCE_ENABLED", True)
    monkeypatch.setattr(lu.settings, "LONELINESS_UTTERANCE_MAX_DELTA", 10.0)

    sel = MagicMock()
    sel.fetchall.return_value = []
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[sel, MagicMock()])
    log = MagicMock()
    log.bind = MagicMock(return_value=log)

    prof = {"loneliness_score": 35.0}
    uid = "00000000-0000-0000-0000-000000000099"
    out = await lu.refresh_loneliness_score(
        db=db,
        user_id=uid,
        profile_row=prof,
        trace_id="tr",
        log=log,
        user_text="我今天特别孤独",
    )
    assert out["loneliness_score"] == 45.0
