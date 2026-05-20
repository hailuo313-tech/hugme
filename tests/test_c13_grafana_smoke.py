"""C-13: Grafana dashboard and alerting smoke."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from services.grafana_integration import (
    C13_CHECKLIST_IDS,
    CORE_METRICS,
    DASHBOARD_REQUIRED_PANELS,
    MONITORING_FILES,
    REQUIRED_ALERTS,
    integration_contract,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "c13_grafana_checklist.json"
DOC = ROOT / "docs" / "C13_GRAFANA_WALKTHROUGH.md"
REPORT = ROOT / "docs" / "C13_INSPECTION_REPORT.md"
ISSUES = ROOT / "docs" / "C13_GRAFANA_ISSUES.md"


def _load() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def test_checklist_count():
    assert len(C13_CHECKLIST_IDS) == 8
    assert len(_load()["items"]) == 8


def test_core_metrics_six():
    assert len(CORE_METRICS) == 6


def test_required_alerts_count():
    assert len(REQUIRED_ALERTS) == 14


def test_monitoring_files_exist():
    for rel in MONITORING_FILES:
        assert (ROOT / rel).is_file(), rel


def test_alerts_yaml_names():
    text = (ROOT / "monitoring/alerts/eris-alerts.yml").read_text(encoding="utf-8")
    found = set(re.findall(r"^\s+- alert:\s+(\w+)", text, re.MULTILINE))
    for name in REQUIRED_ALERTS:
        assert name in found


def test_dashboard_panels():
    data = json.loads(
        (ROOT / "monitoring/grafana-dashboard-eris-mvp.json").read_text(encoding="utf-8")
    )
    titles = {p.get("title") for p in data["panels"]}
    for panel in DASHBOARD_REQUIRED_PANELS:
        assert panel in titles


def test_llm_panels_queries():
    data = json.loads(
        (ROOT / "monitoring/grafana-dashboard-eris-mvp.json").read_text(encoding="utf-8")
    )
    blob = json.dumps(data)
    assert "eris_llm_requests_total" in blob
    assert "eris_llm_request_duration_seconds_bucket" in blob


def test_docs_exist():
    assert DOC.is_file()
    assert REPORT.is_file()
    assert ISSUES.is_file()


def test_contract():
    c = integration_contract()
    assert len(c["core_metrics"]) == 6
    assert "ErisP0HandoffOld" in c["required_alerts"]
