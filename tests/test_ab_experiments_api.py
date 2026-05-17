"""P3 A/B experiments API."""
from __future__ import annotations

from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.ab_experiments import router
from api.admin import require_operator
from core.database import get_db

EXPERIMENT_ID = "00000000-0000-0000-0000-000000000701"
VARIANT_ID = "00000000-0000-0000-0000-000000000702"
ASSIGNMENT_ID = "00000000-0000-0000-0000-000000000703"
USER_ID = "00000000-0000-0000-0000-000000000704"
OPERATOR_ID = "00000000-0000-0000-0000-000000000705"
EVENT_ID = "00000000-0000-0000-0000-000000000706"


def _row(data: dict[str, Any]) -> MagicMock:
    row = MagicMock()
    row._mapping = data
    return row


def _result(*, rows: list[Any] | None = None, one: Any | None = None) -> MagicMock:
    res = MagicMock()
    res.fetchall.return_value = rows or []
    res.fetchone.return_value = one
    return res


def _experiment_row(**overrides: Any) -> MagicMock:
    data = {
        "id": EXPERIMENT_ID,
        "experiment_key": "ops_reply_tone",
        "name": "Ops reply tone",
        "description": "Tone test",
        "status": "draft",
        "owner_operator_id": OPERATOR_ID,
        "target_rules": {},
        "start_at": None,
        "end_at": None,
        "created_at": "2026-05-16T00:00:00",
        "updated_at": "2026-05-16T00:00:00",
    }
    data.update(overrides)
    return _row(data)


def _variant_row(**overrides: Any) -> MagicMock:
    data = {
        "id": VARIANT_ID,
        "experiment_id": EXPERIMENT_ID,
        "variant_key": "control",
        "name": "Control",
        "weight": 10000,
        "config": {},
        "is_control": True,
        "created_at": "2026-05-16T00:00:00",
        "updated_at": "2026-05-16T00:00:00",
    }
    data.update(overrides)
    return _row(data)


def _assignment_row(**overrides: Any) -> MagicMock:
    data = {
        "id": ASSIGNMENT_ID,
        "experiment_id": EXPERIMENT_ID,
        "variant_id": VARIANT_ID,
        "user_id": USER_ID,
        "assignment_key": None,
        "context": {},
        "assigned_at": "2026-05-16T00:00:00",
    }
    data.update(overrides)
    return _row(data)


def _event_row(**overrides: Any) -> MagicMock:
    data = {
        "id": EVENT_ID,
        "experiment_id": EXPERIMENT_ID,
        "variant_id": VARIANT_ID,
        "assignment_id": ASSIGNMENT_ID,
        "user_id": USER_ID,
        "event_type": "conversion",
        "event_value": 1.0,
        "metadata": {},
        "occurred_at": "2026-05-16T00:00:00",
        "created_at": "2026-05-16T00:00:00",
    }
    data.update(overrides)
    return _row(data)


def _app(db: Any, *, with_auth: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/ab-experiments")

    async def _fake_db() -> AsyncGenerator[Any, None]:
        yield db

    app.dependency_overrides[get_db] = _fake_db

    if with_auth:

        async def _fake_operator() -> dict:
            return {"sub": OPERATOR_ID, "type": "operator", "role": "admin"}

        app.dependency_overrides[require_operator] = _fake_operator

    return app


def test_ab_experiments_requires_operator_token():
    db = MagicMock()
    client = TestClient(_app(db, with_auth=False))

    r = client.get("/api/v1/ab-experiments")

    assert r.status_code == 401


def test_create_experiment_inserts_jsonb_owner_and_commits():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(one=_experiment_row(status="running")))
    db.commit = AsyncMock()
    client = TestClient(_app(db))

    r = client.post(
        "/api/v1/ab-experiments",
        json={
            "experiment_key": "ops_reply_tone",
            "name": "Ops reply tone",
            "description": "Tone test",
            "status": "running",
            "target_rules": {"surface": "ops-ai"},
        },
    )

    assert r.status_code == 201, r.text
    params = db.execute.await_args.args[1]
    assert params["owner_operator_id"] == OPERATOR_ID
    assert params["target_rules"] == '{"surface": "ops-ai"}'
    db.commit.assert_awaited_once()


def test_list_experiments_filters_status_and_key():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(rows=[_experiment_row(status="running")]))
    client = TestClient(_app(db))

    r = client.get(
        "/api/v1/ab-experiments",
        params={"status": "running", "experiment_key": "ops_reply_tone"},
    )

    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["status"] == "running"
    params = db.execute.await_args.args[1]
    assert params["status"] == "running"
    assert params["experiment_key"] == "ops_reply_tone"


def test_patch_experiment_updates_status_and_target_rules():
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=_result(
            one=_experiment_row(status="paused", target_rules={"vip_min": 1})
        )
    )
    db.commit = AsyncMock()
    client = TestClient(_app(db))

    r = client.patch(
        f"/api/v1/ab-experiments/{EXPERIMENT_ID}",
        json={"status": "paused", "target_rules": {"vip_min": 1}},
    )

    assert r.status_code == 200, r.text
    sql = str(db.execute.await_args.args[0])
    assert "target_rules = CAST(:target_rules AS jsonb)" in sql
    assert "updated_at = NOW()" in sql
    assert db.execute.await_args.args[1]["target_rules"] == '{"vip_min": 1}'
    db.commit.assert_awaited_once()


def test_create_variant_inserts_config_jsonb():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(one=_variant_row()))
    db.commit = AsyncMock()
    client = TestClient(_app(db))

    r = client.post(
        f"/api/v1/ab-experiments/{EXPERIMENT_ID}/variants",
        json={
            "variant_key": "control",
            "name": "Control",
            "weight": 10000,
            "config": {"tone": "warm"},
            "is_control": True,
        },
    )

    assert r.status_code == 201, r.text
    params = db.execute.await_args.args[1]
    assert params["experiment_id"] == EXPERIMENT_ID
    assert params["config"] == '{"tone": "warm"}'
    db.commit.assert_awaited_once()


def test_list_variants_returns_items():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(rows=[_variant_row()]))
    client = TestClient(_app(db))

    r = client.get(f"/api/v1/ab-experiments/{EXPERIMENT_ID}/variants")

    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["variant_key"] == "control"


def test_assign_variant_returns_existing_assignment_without_commit():
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=_result(
            one=_assignment_row(variant_key="control", variant_name="Control", config={})
        )
    )
    db.commit = AsyncMock()
    client = TestClient(_app(db))

    r = client.post(
        f"/api/v1/ab-experiments/{EXPERIMENT_ID}/assign",
        json={"user_id": USER_ID},
    )

    assert r.status_code == 200, r.text
    assert r.json()["created"] is False
    db.commit.assert_not_awaited()


def test_assign_variant_creates_deterministic_assignment():
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _result(one=None),
            _result(one=_experiment_row(status="running")),
            _result(rows=[_variant_row(config={"tone": "warm"})]),
            _result(one=_assignment_row()),
        ]
    )
    db.commit = AsyncMock()
    client = TestClient(_app(db))

    r = client.post(
        f"/api/v1/ab-experiments/{EXPERIMENT_ID}/assign",
        json={"user_id": USER_ID, "context": {"surface": "ops-ai"}},
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] is True
    assert body["assignment"]["variant_key"] == "control"
    params = db.execute.await_args_list[-1].args[1]
    assert params["variant_id"] == VARIANT_ID
    assert params["context"] == '{"surface": "ops-ai"}'
    db.commit.assert_awaited_once()


def test_assign_variant_rejects_non_running_experiment():
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _result(one=None),
            _result(one=_experiment_row(status="paused")),
        ]
    )
    client = TestClient(_app(db))

    r = client.post(
        f"/api/v1/ab-experiments/{EXPERIMENT_ID}/assign",
        json={"user_id": USER_ID},
    )

    assert r.status_code == 409
    assert r.json()["detail"] == "experiment is not running"


def test_create_event_inserts_metadata_jsonb():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(one=_event_row()))
    db.commit = AsyncMock()
    client = TestClient(_app(db))

    r = client.post(
        f"/api/v1/ab-experiments/{EXPERIMENT_ID}/events",
        json={
            "variant_id": VARIANT_ID,
            "assignment_id": ASSIGNMENT_ID,
            "user_id": USER_ID,
            "event_type": "conversion",
            "event_value": 1,
            "metadata": {"source": "reply"},
        },
    )

    assert r.status_code == 201, r.text
    params = db.execute.await_args.args[1]
    assert params["metadata"] == '{"source": "reply"}'
    db.commit.assert_awaited_once()


def test_list_events_filters_event_type():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(rows=[_event_row()]))
    client = TestClient(_app(db))

    r = client.get(
        f"/api/v1/ab-experiments/{EXPERIMENT_ID}/events",
        params={"event_type": "conversion"},
    )

    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["event_type"] == "conversion"
    assert db.execute.await_args.args[1]["event_type"] == "conversion"


def test_validation_rejects_invalid_status_weight_and_missing_assignment_key():
    db = MagicMock()
    client = TestClient(_app(db))

    r = client.post(
        "/api/v1/ab-experiments",
        json={"experiment_key": "x", "name": "X", "status": "bad"},
    )
    assert r.status_code == 422

    r = client.post(
        f"/api/v1/ab-experiments/{EXPERIMENT_ID}/variants",
        json={"variant_key": "a", "name": "A", "weight": 10001},
    )
    assert r.status_code == 422

    r = client.post(f"/api/v1/ab-experiments/{EXPERIMENT_ID}/assign", json={})
    assert r.status_code == 422
