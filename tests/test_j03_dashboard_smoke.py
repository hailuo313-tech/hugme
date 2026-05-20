"""C-10: J-03 dashboard integration smoke."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from main import app as main_app
from services.dashboard_integration import (
    DASHBOARD_CHECKLIST_IDS,
    HANDOFF_API_PATHS,
    TAKEOVER_SLA_MS,
    integration_contract,
    sort_conversations_for_dashboard,
    sql_order_clause_for_dashboard,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "j03_dashboard_smoke.json"
DOC = ROOT / "docs" / "J03_DASHBOARD_INTEGRATION.md"
CHECKLIST = ROOT / "docs" / "C10_DASHBOARD_CHECKLIST_SIGNOFF.md"


def _load() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _load()["sort_cases"], ids=[c["id"] for c in _load()["sort_cases"]])
def test_dashboard_sort_cases(case: dict):
    sorted_rows = sort_conversations_for_dashboard(case["input"])
    assert sorted_rows[0]["conversation_id"] == case["expect_first"]


def test_takeover_sla_ms():
    data = _load()
    assert data["takeover_sla_ms"] == TAKEOVER_SLA_MS == 3000


def test_sql_order_has_waiting_operator_first():
    sql = sql_order_clause_for_dashboard()
    assert "WAITING_OPERATOR" in sql
    assert "vip_level" in sql


def test_checklist_count():
    assert len(DASHBOARD_CHECKLIST_IDS) == 10


def test_docs_exist():
    assert DOC.is_file()
    assert CHECKLIST.is_file()


def _route_paths(application: FastAPI) -> set[str]:
    paths: set[str] = set()
    for route in application.routes:
        if isinstance(route, APIRoute):
            methods = ",".join(sorted(route.methods or []))
            paths.add(f"{methods} {route.path}")
    return paths


def test_main_app_exposes_handoff_and_admin():
    paths = _route_paths(main_app)
    assert any("/api/v1/admin/conversations" in p for p in paths)
    assert any("/handoff/{task_id}/lock" in p for p in paths)
    assert any("/ws/operators/tasks" in p for p in paths)


def test_handoff_paths_in_contract():
    c = integration_contract()
    assert len(c["handoff_api_paths"]) == 3
    assert c["takeover_sla_ms"] == 3000
