"""Fixed auto-reply admin: rule sort_order behavior."""
from __future__ import annotations

from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.admin import require_operator
from api.fixed_auto_replies_admin import router
from core.database import get_db


def _result(scalar: Any = None, rows: list[Any] | None = None):
    res = MagicMock()
    res.scalar.return_value = scalar
    res.fetchall.return_value = rows or []
    return res


def _db_with(results: list[Any]):
    db = MagicMock()
    db.execute = AsyncMock(side_effect=list(results))
    db.commit = AsyncMock()
    return db


def _build_app(db: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/fixed-auto-replies/admin")

    async def _fake_get_db() -> AsyncGenerator[Any, None]:
        yield db

    async def _fake_operator() -> dict:
        return {"sub": "op-test", "username": "test_op", "role": "admin", "type": "operator"}

    app.dependency_overrides[get_db] = _fake_get_db
    app.dependency_overrides[require_operator] = _fake_operator
    return app


@pytest.mark.parametrize("max_sort,expected", [(0, 1), (5, 6), (21, 22)])
def test_create_rule_assigns_next_sort_order(max_sort: int, expected: int):
    import services.fixed_auto_reply_service as svc

    svc._schema_ready = True
    db = _db_with([_result(scalar=max_sort), _result(scalar=None)])
    app = _build_app(db)
    client = TestClient(app)
    response = client.post(
        "/api/v1/fixed-auto-replies/admin/rules",
        json={
            "name": "测试规则",
            "text_content": "hello",
            "delay_seconds": 30,
            "is_active": False,
            "sort_order": 0,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sort_order"] == expected

    insert_call = db.execute.await_args_list[-1]
    assert insert_call.args[1]["sort_order"] == expected


def test_update_rule_does_not_require_sort_order():
    import services.fixed_auto_reply_service as svc

    svc._schema_ready = True
    db = _db_with(
        [
            MagicMock(
                mappings=MagicMock(
                    return_value=MagicMock(first=MagicMock(return_value={"is_active": True}))
                )
            ),
            _result(scalar=None),
        ]
    )
    app = _build_app(db)
    client = TestClient(app)
    rule_id = "11111111-1111-1111-1111-111111111111"
    response = client.patch(
        f"/api/v1/fixed-auto-replies/admin/rules/{rule_id}",
        json={"name": "改名", "delay_seconds": 120},
    )
    assert response.status_code == 200, response.text
    update_sql = db.execute.await_args_list[-1].args[0].text
    assert "sort_order" not in update_sql
