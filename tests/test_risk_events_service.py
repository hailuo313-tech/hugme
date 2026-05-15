"""V001-P0-3：risk_level 派生与 severity → score 映射。"""
from __future__ import annotations

import pytest

from services.risk_events import (
    risk_level_from_score,
    severity_to_risk_score,
)


@pytest.mark.parametrize(
    "score,level",
    [
        (0, "normal"),
        (39, "normal"),
        (40, "elevated"),
        (69, "elevated"),
        (70, "high"),
        (89, "high"),
        (90, "critical"),
        (100, "critical"),
    ],
)
def test_risk_level_from_score(score: int, level: str):
    assert risk_level_from_score(score) == level


@pytest.mark.parametrize(
    "severity,score",
    [
        ("P0", 95),
        ("p0", 95),
        ("P1", 75),
        ("P2", 55),
        ("P3", 35),
        (None, 75),
        ("P9", 50),
    ],
)
def test_severity_to_risk_score(severity: str | None, score: int):
    assert severity_to_risk_score(severity) == score
