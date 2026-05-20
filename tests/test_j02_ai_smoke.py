"""C-08: J-02 AI pipeline smoke — 8 fixtures, <8s budget."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from services.ai_pipeline_smoke import LATENCY_BUDGET_MS, run_pipeline_case

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "j02_ai_smoke.json"


def _fixtures() -> list[dict]:
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    return list(data["fixtures"])


@pytest.mark.parametrize("fix", _fixtures(), ids=[f["id"] for f in _fixtures()])
def test_j02_fixture(fix: dict):
    res = run_pipeline_case(fix)
    assert res.pass_case, f"{fix['id']}: expect mismatch outcome={res.outcome}"
    assert res.within_budget, f"{fix['id']}: total_ms={res.total_ms} >= budget"


def test_j02_fixture_count():
    assert len(_fixtures()) == 8


def test_j02_latency_budget_constant():
    assert LATENCY_BUDGET_MS == 8000


def test_j02_cli_runner_exit_zero():
    script = ROOT / "scripts" / "j02_ai_smoke.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--no-report"],
        cwd=str(ROOT),
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "app")},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_j02_latency_stress_under_budget():
    fix = next(f for f in _fixtures() if f["id"] == "J02-08")
    res = run_pipeline_case(fix)
    assert res.outcome == "reply"
    assert res.total_ms < 8000
    assert res.timings_ms.get("llm_stub", 0) >= 1900
