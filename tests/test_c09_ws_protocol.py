"""C-09: ws_protocol.md conformance vs implementation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import importlib

realtime = importlib.import_module("api.realtime")
from services.ws_operator_task_delta import TRACKED_FIELDS
from services.ws_protocol_conformance import (
    CLIENT_EVENT_TYPES,
    OPEN_TASK_STATUSES,
    POLL_INTERVAL_MS,
    SERVER_EVENT_TYPES,
    TASK_REQUIRED_FIELDS,
    TRACKED_DELTA_FIELDS,
    implementation_contract,
    validate_client_event,
    validate_server_event,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "c09_ws_protocol.json"
DOC = ROOT / "docs" / "ws_protocol.md"


def _load() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "case",
    _load()["valid_server_events"],
    ids=[c["id"] for c in _load()["valid_server_events"]],
)
def test_valid_server_events(case: dict):
    errs = validate_server_event(case["payload"])
    assert errs == [], f"{case['id']}: {errs}"


@pytest.mark.parametrize(
    "case",
    _load()["valid_client_events"],
    ids=[c["id"] for c in _load()["valid_client_events"]],
)
def test_valid_client_events(case: dict):
    assert validate_client_event(case["payload"]) == []


@pytest.mark.parametrize(
    "case",
    _load()["invalid_server_events"],
    ids=[c["id"] for c in _load()["invalid_server_events"]],
)
def test_invalid_server_events_rejected(case: dict):
    assert validate_server_event(case["payload"])


def test_ws_protocol_doc_exists():
    assert DOC.is_file()
    text = DOC.read_text(encoding="utf-8")
    for t in SERVER_EVENT_TYPES:
        assert t in text


def test_implementation_matches_contract():
    c = implementation_contract()
    assert c["ws_path"] == "/ws/operators/tasks"
    assert c["poll_interval_ms"] == POLL_INTERVAL_MS
    assert set(c["open_task_statuses"]) == set(OPEN_TASK_STATUSES)
    assert set(c["tracked_delta_fields"]) == TRACKED_DELTA_FIELDS
    assert set(TRACKED_FIELDS) == TRACKED_DELTA_FIELDS


def test_realtime_constants_align():
    assert int(realtime.POLL_INTERVAL_SECONDS * 1000) == POLL_INTERVAL_MS
    assert tuple(realtime.OPEN_TASK_STATUSES) == OPEN_TASK_STATUSES
    routes = [getattr(r, "path", "") for r in realtime.router.routes]
    assert "/ws/operators/tasks" in routes


def test_server_event_type_count():
    assert len(SERVER_EVENT_TYPES) == 6


def test_task_required_field_count():
    assert len(TASK_REQUIRED_FIELDS) == 14


def test_client_event_types():
    assert CLIENT_EVENT_TYPES == {"ping", "task.ack"}
