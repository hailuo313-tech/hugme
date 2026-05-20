"""C-12: E2E/CI nightly integration smoke."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.e2e_ci_integration import (
    C12_CHECKLIST_IDS,
    E2E_FULL_SCRIPT,
    E2E_SMOKE_SCRIPT,
    NIGHTLY_STABILITY_DAYS,
    NIGHTLY_WORKFLOW,
    PERF_LOAD_SCRIPT,
    PR_WORKFLOW,
    integration_contract,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "c12_e2e_ci_checklist.json"
DOC = ROOT / "docs" / "C12_E2E_CI_REVIEW.md"
REPORT = ROOT / "docs" / "C12_INSPECTION_REPORT.md"
STABILITY = ROOT / "fixtures" / "c12_nightly_stability.json"


def _load() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def test_checklist_count():
    assert len(C12_CHECKLIST_IDS) == 8
    assert len(_load()["items"]) == 8


def test_stability_days_match_fixture():
    data = _load()
    assert data["stability_days"] == NIGHTLY_STABILITY_DAYS == 3


def test_scripts_exist():
    for rel in (E2E_FULL_SCRIPT, E2E_SMOKE_SCRIPT, PERF_LOAD_SCRIPT):
        assert (ROOT / rel).is_file(), rel


def test_workflows_exist():
    assert (ROOT / PR_WORKFLOW).is_file()
    assert (ROOT / NIGHTLY_WORKFLOW).is_file()


def test_run_sh_smoke_hooks():
    text = (ROOT / E2E_FULL_SCRIPT).read_text(encoding="utf-8")
    assert "E2E_CHAT_ROUNDS" in text
    assert "E2E_SKIP_STRIPE" in text
    assert "handoff lock API" in text


def test_smoke_sh_delegates():
    text = (ROOT / E2E_SMOKE_SCRIPT).read_text(encoding="utf-8")
    assert "run.sh" in text
    assert "E2E_CHAT_ROUNDS" in text


def test_perf_outside_ci_documented():
    text = (ROOT / PERF_LOAD_SCRIPT).read_text(encoding="utf-8")
    assert "outside CI" in text or "outside ci" in text.lower()


def test_nightly_workflow_has_schedule_and_smoke():
    text = (ROOT / NIGHTLY_WORKFLOW).read_text(encoding="utf-8")
    assert "schedule:" in text
    assert "e2e-smoke" in text
    assert "LLM_ECHO_FALLBACK" in text


def test_docs_exist():
    assert DOC.is_file()
    assert REPORT.is_file()
    assert STABILITY.is_file()


def test_contract_shape():
    c = integration_contract()
    assert c["nightly_stability_days"] == 3
    assert "c12-audit" in c["ci_jobs"]
    assert "e2e-smoke" in c["ci_jobs"]
