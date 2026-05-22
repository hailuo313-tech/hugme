"""D6-2 单元测试：``services.stripe_webhook``。

只覆盖纯逻辑分支（验签 / 抢占 / 分发 / checkout_completed 主路径）。
真实 SQL、Stripe API 都用 mock 替代；不依赖 docker。
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import stripe_webhook as sw
from services.stripe_webhook import SignatureError


# ── 工具：构造一个看起来像 SQLAlchemy AsyncSession 的 mock ───────────


def _make_session_mock(execute_results: list[Any] | None = None) -> MagicMock:
    """``db.execute(...)`` 是 async；返回结果对象的 ``.fetchone()`` 同步返回数据。

    ``execute_results`` 按调用顺序提供每次的返回结果（None 表示返回 result.fetchone() == None）。
    """
    session = MagicMock()
    results = list(execute_results or [])

    async def _execute(*args, **kwargs):  # noqa: ANN001
        nonlocal results
        res = MagicMock()
        val = results.pop(0) if results else None
        res.fetchone = MagicMock(return_value=val)
        return res

    session.execute = AsyncMock(side_effect=_execute)
    session.commit = AsyncMock(return_value=None)
    return session


# ── verify_and_parse_event ────────────────────────────────────────


def test_verify_raises_when_secret_missing():
    with patch.object(sw.settings, "STRIPE_WEBHOOK_SECRET", None):
        with pytest.raises(SignatureError, match="not configured"):
            sw.verify_and_parse_event(b"{}", "sig")


def test_verify_raises_on_signature_error():
    fake_exc = sw.stripe.SignatureVerificationError("bad sig", "sig_header")
    with patch.object(sw.settings, "STRIPE_WEBHOOK_SECRET", "whsec_x"), patch.object(
        sw.stripe.Webhook, "construct_event", side_effect=fake_exc
    ):
        with pytest.raises(SignatureError, match="invalid signature"):
            sw.verify_and_parse_event(b"{}", "sig_header")


def test_verify_returns_event_on_success():
    fake_event = {"id": "evt_1", "type": "checkout.session.completed"}
    with patch.object(sw.settings, "STRIPE_WEBHOOK_SECRET", "whsec_x"), patch.object(
        sw.stripe.Webhook, "construct_event", return_value=fake_event
    ):
        out = sw.verify_and_parse_event(b"{}", "sig_header")
    assert out == fake_event


# ── claim_event（幂等） ────────────────────────────────────────────


async def test_claim_event_first_time_returns_true():
    session = _make_session_mock(execute_results=[("evt_1",)])
    ok = await sw.claim_event(
        session,
        event_id="evt_1",
        event_type="checkout.session.completed",
        payload_json="{}",
    )
    assert ok is True
    session.commit.assert_awaited()


async def test_claim_event_duplicate_returns_false():
    # ON CONFLICT DO NOTHING → fetchone() 返回 None
    session = _make_session_mock(execute_results=[None])
    ok = await sw.claim_event(
        session,
        event_id="evt_1",
        event_type="checkout.session.completed",
        payload_json="{}",
    )
    assert ok is False


# ── handle_event 分发 ─────────────────────────────────────────────


async def test_handle_event_unknown_type_marks_ignored():
    session = _make_session_mock(execute_results=[None])  # _mark_result UPDATE
    out = await sw.handle_event(
        session,
        {"id": "evt_2", "type": "customer.created", "data": {"object": {}}},
    )
    assert out == "ignored"


async def test_handle_event_checkout_completed_happy_path():
    """metadata.order_id 找到 → orders 改 paid → users.vip_level += 1。"""
    # 各次 execute 的返回（按 _handle_checkout_completed 内部顺序）：
    # 1) UPDATE orders ... RETURNING user_id → ("user-uuid",)
    # 2) UPDATE users SET vip_level (无 RETURNING)
    # 3) _mark_result UPDATE
    session = _make_session_mock(execute_results=[("user-uuid",), None, None])
    event = {
        "id": "evt_paid_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_1",
                "metadata": {"order_id": "ord-uuid", "user_id": "user-uuid"},
            }
        },
    }
    out = await sw.handle_event(session, event)
    assert out == "processed"
    # vip_level UPDATE 应该被调用 → 至少 2 次 execute
    assert session.execute.await_count >= 2


async def test_handle_event_checkout_completed_recalculates_paid_user_to_s():
    """P2-10: paid T1 user with >= $200 lifetime spend recalculates to S."""
    session = _make_session_mock(
        execute_results=[
            ("user-uuid",),  # UPDATE orders ... RETURNING user_id
            (True, False),  # minor protection user row
            None,  # user_profiles vip upsert
            (20000,),  # paid lifetime spend in cents
            (1, {"country_code": "US"}, "B", None),  # profile signals
            None,  # user_profiles level/chat_route update
            None,  # _mark_result
        ]
    )
    event = {
        "id": "evt_paid_s",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_s",
                "metadata": {"order_id": "ord-uuid", "user_id": "user-uuid"},
            }
        },
    }

    with patch.object(sw, "notify_user_upgrade", new=AsyncMock()) as notify:
        out = await sw.handle_event(session, event)

    assert out == "processed"
    level_updates = [
        call.args[1]
        for call in session.execute.await_args_list
        if len(call.args) > 1
        and isinstance(call.args[1], dict)
        and call.args[1].get("user_level") == "S"
    ]
    assert level_updates
    assert level_updates[0]["chat_route"] == "manual_premium"
    assert level_updates[0]["lifetime_spend_usd"] == 200.0
    notify.assert_awaited_once_with(
        user_id="user-uuid",
        previous_level="B",
        new_level="S",
        reason="payment_completed",
    )


async def test_handle_event_checkout_completed_records_payment_attribution():
    session = _make_session_mock(
        execute_results=[
            ("user-uuid", "trk_1", 9900, "USD"),
            (True, False),
            None,
            (9900,),
            (1, {"country_code": "US"}, "A", None),
            None,
            None,
            None,
        ]
    )
    event = {
        "id": "evt_paid_attr",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_attr",
                "metadata": {"order_id": "ord-uuid", "attribution_tracking_id": "trk_1"},
            }
        },
    }

    out = await sw.handle_event(session, event)

    assert out == "processed"
    attribution_calls = [
        call
        for call in session.execute.await_args_list
        if "INSERT INTO attribution_events" in str(call.args[0])
    ]
    assert attribution_calls
    params = attribution_calls[0].args[1]
    assert params["event_type"] == "payment"
    assert params["tracking_id"] == "trk_1"
    assert params["amount_cents"] == 9900


async def test_handle_event_checkout_completed_falls_back_to_session_id():
    """metadata 里没 order_id 时按 provider_order_id 反查 orders。"""
    # 1) SELECT id FROM orders WHERE provider_order_id → ("ord-uuid",)
    # 2) UPDATE orders ... RETURNING user_id → ("user-uuid",)
    # 3) UPDATE users vip_level
    # 4) _mark_result UPDATE
    session = _make_session_mock(
        execute_results=[("ord-uuid",), ("user-uuid",), None, None]
    )
    event = {
        "id": "evt_paid_2",
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_test_2", "metadata": {}}},
    }
    out = await sw.handle_event(session, event)
    assert out == "processed"


async def test_handle_event_checkout_completed_idempotent_when_already_paid():
    """orders 已是 paid（UPDATE 影响 0 行），仍要返回 processed，不抛错。"""
    # 1) UPDATE orders ... RETURNING → None（已是 paid）
    # 2) SELECT 1 FROM orders WHERE id → (1,)   存在
    # 3) _mark_result UPDATE
    session = _make_session_mock(execute_results=[None, (1,), None])
    event = {
        "id": "evt_paid_3",
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_x", "metadata": {"order_id": "ord-uuid"}}},
    }
    out = await sw.handle_event(session, event)
    assert out == "processed"


async def test_handle_event_failure_marks_failed():
    """业务处理抛异常 → 不冒泡 + 写 result='failed'。"""
    session = _make_session_mock(execute_results=[])
    session.execute = AsyncMock(side_effect=RuntimeError("boom"))
    event = {
        "id": "evt_paid_4",
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_x", "metadata": {"order_id": "ord-uuid"}}},
    }
    out = await sw.handle_event(session, event)
    assert out == "failed"
