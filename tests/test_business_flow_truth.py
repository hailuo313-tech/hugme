from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUSINESS_FLOW = ROOT / "docs" / "product" / "business-flow.html"


def _html() -> str:
    return BUSINESS_FLOW.read_text(encoding="utf-8")


def _task_line(task_id: str) -> str:
    text = _html()
    match = re.search(rf'\{{ id:"{re.escape(task_id)}"[^}}\n]*\}},', text)
    assert match is not None, task_id
    return match.group(0)


def test_open_tracking_tasks_are_not_default_done() -> None:
    for task_id in ("C-12",):
        line = _task_line(task_id)

        assert "baseline:false" in line
        assert "verified:true" not in line


def test_completed_tasks_use_verified_field() -> None:
    for task_id in ("P1-01", "P1-06", "P1-16", "H-03", "H-07", "P2-08", "P5-07"):
        line = _task_line(task_id)

        assert "baseline:true" in line
        assert "verified:true" in line


def test_p2_08_mentions_python_pytest_not_typescript() -> None:
    line = _task_line("P2-08")

    assert "tests/test_level_engine.py" in line
    assert "level_engine.test.ts" not in line


def test_no_hardcoded_completion_arrays_remain() -> None:
    text = _html()

    for marker in (
        "p1Completed",
        "p2Completed",
        "p3Completed",
        "p4Completed",
        "AdditionalCompleted",
    ):
        assert marker not in text


def test_done_defaults_are_loaded_from_verified_tasks_only() -> None:
    text = _html()

    assert "eris-business-flow-done-v3" in text
    assert "DEFAULT_DONE_IDS = new Set(TASKS.filter(t => t.verified === true)" in text
    assert "TASKS.filter(t => t.baseline)" not in text


def test_verified_parallel_rows_render_done() -> None:
    text = _html()

    assert "if (task && task.verified === true) return { ...p, t: 'done' };" in text
