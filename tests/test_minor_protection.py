from __future__ import annotations

from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.notifications import router as notifications_router
from api.payments import router as payments_router
from core.database import get_db
from services.minor_protection import (
    AGE_VERIFICATION_REQUIRED_DETAIL,
    MINOR_BLOCK_DETAIL,
    contains_adult_content,
    detect_minor_self_disclosure,
    evaluate_inbound_minor_protection,
)
from services import stripe_webhook as sw

USER_ID = "00000000-0000-0000-0000-000000000801"


def _result(*, one: Any | None = None, mappings_one: Any | None = None) -> MagicMock:
    res = MagicMock()
    res.fetchone.return_value = one
    mappings = MagicMock()
    mappings.fetchone.return_value = mappings_one
    res.mappings.return_value = mappings
    return res


def _app(router, prefix: str, db: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix=prefix)

    async def _fake_db() -> AsyncGenerator[Any, None]:
        yield db

    app.dependency_overrides[get_db] = _fake_db
    return app


def test_minor_detection_and_adult_content_rules():
    assert detect_minor_self_disclosure("I'm 16 years old")
    assert detect_minor_self_disclosure("我十六岁")
    assert detect_minor_self_disclosure("未成年")
    assert not detect_minor_self_disclosure("I am 20 years old")
    assert contains_adult_content("send nudes")
    assert contains_adult_content("我们性聊")


@pytest.mark.asyncio
async def test_inbound_minor_disclosure_updates_user_and_blocks_adult_content():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result())
    db.commit = AsyncMock()

    decision = await evaluate_inbound_minor_protection(
        db,
        user_id=USER_ID,
        text_value="I'm 16 years old and want sexy chat",
        is_minor_suspected=False,
    )

    assert decision.blocked is True
    assert decision.reason == "minor_protection:adult_content"
    assert decision.updated_user is True
    sql = str(db.execute.await_args.args[0])
    assert "is_minor_suspected = TRUE" in sql
    db.commit.assert_awaited_once()


def test_create_order_blocks_age_unverified_user():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(one=(USER_ID, "active", False, False)))
    client = TestClient(_app(payments_router, "/api/v1", db))

    r = client.post(
        "/api/v1/orders",
        json={
            "user_id": USER_ID,
            "product_id": "vip",
            "amount": 499,
            "currency": "USD",
        },
    )

    assert r.status_code == 403
    assert r.json()["detail"] == AGE_VERIFICATION_REQUIRED_DETAIL


def test_create_order_blocks_suspected_minor():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(one=(USER_ID, "active", True, True)))
    client = TestClient(_app(payments_router, "/api/v1", db))

    r = client.post(
        "/api/v1/orders",
        json={
            "user_id": USER_ID,
            "product_id": "vip",
            "amount": 499,
            "currency": "USD",
        },
    )

    assert r.status_code == 403
    assert r.json()["detail"] == MINOR_BLOCK_DETAIL


def test_create_order_verified_adult_creates_checkout_session():
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _result(one=(USER_ID, "active", True, False)),
            _result(),
            _result(),
        ]
    )
    db.commit = AsyncMock()
    client = TestClient(_app(payments_router, "/api/v1", db))
    fake_session = MagicMock(id="cs_test", url="https://checkout.example/test")

    with (
        patch.object(payments_router.routes[0].endpoint.__globals__["settings"], "STRIPE_SECRET_KEY", "sk_test"),
        patch("api.payments.stripe.checkout.Session.create", return_value=fake_session),
    ):
        r = client.post(
            "/api/v1/orders",
            json={
                "user_id": USER_ID,
                "product_id": "vip",
                "amount": 499,
                "currency": "USD",
            },
        )

    assert r.status_code == 200, r.text
    assert r.json()["checkout_url"] == "https://checkout.example/test"
    assert db.commit.await_count == 2


def test_schedule_notification_blocks_suspected_minor():
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=_result(
            mappings_one={
                "id": USER_ID,
                "channel": "telegram",
                "external_id": "tg_1",
                "status": "active",
                "notification_opt_in": True,
                "opt_out_marketing": False,
                "is_minor_suspected": True,
                "risk_level": "normal",
                "timezone": "UTC",
            }
        )
    )
    client = TestClient(_app(notifications_router, "/api/v1/notifications", db))

    r = client.post(
        "/api/v1/notifications/schedule",
        json={
            "user_id": USER_ID,
            "channel": "telegram",
            "notification_type": "silent_reactivation",
        },
    )

    assert r.status_code == 409
    assert r.json()["detail"] == MINOR_BLOCK_DETAIL


@pytest.mark.asyncio
async def test_stripe_webhook_blocks_minor_vip_upgrade():
    session = MagicMock()
    session.commit = AsyncMock()

    results = [
        ("user-uuid",),
        (False, True),
        None,
        None,
    ]

    async def _execute(*_args, **_kwargs):
        res = MagicMock()
        val = results.pop(0) if results else None
        res.fetchone.return_value = val
        return res

    session.execute = AsyncMock(side_effect=_execute)
    event = {
        "id": "evt_paid_minor",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_minor",
                "metadata": {"order_id": "order-uuid"},
            }
        },
    }

    out = await sw.handle_event(session, event)

    assert out == "processed"
    sql_text = "\n".join(str(call.args[0]) for call in session.execute.await_args_list)
    assert "blocked_minor" in sql_text
    assert "vip_level" not in sql_text
