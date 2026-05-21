"""C-14: pre-launch final inspection smoke tests."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from services.prelaunch_integration import (
    BASELINE_TASK_IDS,
    C14_CHECKLIST_IDS,
    CANONICAL_PATHS,
    CURSOR_DELIVERABLES,
    FORBIDDEN_TOP_LEVEL_DIRS,
    PR_GATE_JOBS,
    integration_contract,
)

ROOT = Path(__file__).resolve().parents[1]
BF = ROOT / "docs" / "product" / "business-flow.html"


def test_checklist_count():
    data = json.loads((ROOT / "fixtures/c14_prelaunch_checklist.json").read_text(encoding="utf-8"))
    assert len(C14_CHECKLIST_IDS) == 10
    assert len(data["items"]) == 10


def test_no_forbidden_dirs():
    for name in FORBIDDEN_TOP_LEVEL_DIRS:
        assert not (ROOT / name).exists()


def test_pr_gate_jobs():
    text = (ROOT / ".github/workflows/pr-required-gates.yml").read_text(encoding="utf-8")
    for job in PR_GATE_JOBS:
        assert job in text


def test_cursor_deliverables_exist():
    for paths in CURSOR_DELIVERABLES.values():
        for rel in paths:
            assert (ROOT / rel).is_file(), rel


def test_c12_stability_tracking_is_truthful():
    data = json.loads((ROOT / "fixtures/c12_nightly_stability.json").read_text(encoding="utf-8"))
    if data["stability_met"]:
        assert all(run["trigger"] == "schedule" for run in data["runs"][-3:])
    else:
        assert data["open_issue"]["status"] == "waiting_for_scheduled_runs"


def test_business_flow_baselines():
    text = BF.read_text(encoding="utf-8")
    for tid in BASELINE_TASK_IDS:
        assert re.search(rf'id:"{tid}"[^}}]*baseline:true', text), tid


def test_contract():
    c = integration_contract()
    assert len(c["canonical_paths"]) >= 10
    assert "C-13" in c["cursor_deliverables"]


def test_c14_docs():
    assert (ROOT / "docs/C14_INSPECTION_REPORT.md").is_file()
    assert (ROOT / "docs/C14_PRELAUNCH_ISSUES.md").is_file()
