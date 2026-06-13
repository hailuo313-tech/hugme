"""C-07: safety redline fixtures — inbound gate removed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.safety_redline_eval import eval_redline, moderation_blocks

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "c07_safety_redlines.json"


def _redlines() -> list[dict]:
    return list(json.loads(FIXTURES.read_text(encoding="utf-8"))["redlines"])


_RL_ROWS = [r for r in _redlines() if r["handler"] != "moderation_self_harm_pass"]


@pytest.mark.parametrize("row", _RL_ROWS, ids=[r["id"] for r in _RL_ROWS])
def test_redline_fixture(row: dict):
    out = eval_redline(row["handler"], row.get("text", ""))
    if "expect_blocked" in row:
        assert out["blocked"] is row["expect_blocked"], f"{row['id']} {out}"
    if "expect_detected" in row:
        assert out["detected"] is row["expect_detected"], f"{row['id']} {out}"


def test_rl04_self_harm_moderation_no_longer_blocks():
    cats = {"self-harm": True, "sexual": False}
    scores = {"self-harm": 0.99, "sexual": 0.01}
    assert moderation_blocks(cats, scores, flagged=True) is False


def test_rl08_sexual_minors_no_longer_blocks():
    cats = {"sexual/minors": True}
    scores = {"sexual/minors": 0.99}
    assert moderation_blocks(cats, scores, flagged=True) is False
