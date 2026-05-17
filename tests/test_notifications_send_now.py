from __future__ import annotations

from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.notifications import router
from core.database import get_db
from services.minor_protection import MINOR_BLOCK_DETAIL

USER_ID = "00000000-0000-0000-0000-000000000901"


def _result(
    *,
    one: Any | None = None,
    mappings_one: Any | None = None,
    mappings_all: list[Any] | None = None,
) -> MagicMock:
    res = MagicMock()
    res.fetchone.return_value = one
    mappings = MagicMock()
    mappings.fetchone.return_value = mappings_one
    mappings.one.return_value = mappings_one
    mappings.all.return_value = mappings_all or []
    res.mappings.return_value = mappings
    return res


def _active_user(**overrides: Any) -> dict[str, Any]:
    data = {
        "id": USER_ID,
        "channel": "telegram",
        "external_id": "tg_12345",
        "status": "active",
        "notification_opt_in": True,
        "opt_out_marketing": False,
        "is_minor_suspected": False,
        "risk_level": "normal",
        "timezone": "UTC",
    }
    data.update(overrides)
    return data


def _app(db: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/notifications")

    async def _fake_db() -> AsyncGenerator[Any, None]:
        yield db

    app.dependency_overrides[get_db] = _fake_db
    return app


def test_send_now_sends_and_marks_task_sent():
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _result(mappings_one=_active_user()),
            _result(one=None),  # open handoff check
            _result(mappings_one=None),  # S5 profile gate
            _result(mappings_one={"daily_count": 0, "weekly_count": 0}),
            _result(mappings_one=None),  # dedupe
            _result(),  # insert sending task
            _result(),  # mark sent
        ]
    )
    db.commit = AsyncMock()
    client = TestClient(_app(db))

    with (
        patch("api.notifications.settings.TELEGRAM_BOT_TOKEN", "token"),
        patch("api.notifications.send_telegram_text", new=AsyncMock(return_value=7788)) as send_mock,
    ):
        r = client.post(
            "/api/v1/notifications/send-now",
            json={
                "user_id": USER_ID,
                "channel": "telegram",
                "notification_type": "silent_reactivation",
                "payload": {"tier": "D1"},
            },
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "sent"
    assert body["telegram_message_id"] == 7788
    assert body["payload"]["dedupe_key"]
    assert send_mock.await_args.kwargs["chat_id"] == 12345
    assert "No rush" in send_mock.await_args.kwargs["text_content"]
    sql_text = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)
    assert "status = 'sent'" in sql_text
    assert db.commit.await_count >= 2


def test_send_now_rejects_unsupported_type_before_insert():
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _result(mappings_one=_active_user()),
            _result(one=None),
            _result(mappings_one=None),
        ]
    )
    db.commit = AsyncMock()
    client = TestClient(_app(db))

    r = client.post(
        "/api/v1/notifications/send-now",
        json={
            "user_id": USER_ID,
            "channel": "telegram",
            "notification_type": "marketing_blast",
        },
    )

    assert r.status_code == 422
    assert r.json()["detail"] == "Unsupported notification_type"
    db.commit.assert_not_awaited()


def test_send_now_blocks_suspected_minor():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(mappings_one=_active_user(is_minor_suspected=True)))
    client = TestClient(_app(db))

    r = client.post(
        "/api/v1/notifications/send-now",
        json={
            "user_id": USER_ID,
            "channel": "telegram",
            "notification_type": "silent_reactivation",
        },
    )

    assert r.status_code == 409
    assert r.json()["detail"] == MINOR_BLOCK_DETAIL


@patch("services.risk_s5.load_s5_restrictions", new_callable=AsyncMock)
@patch("services.risk_s5.notification_block_reason")
def test_schedule_allows_s5_care_checkin_in_care_window(mock_block, mock_load):
    mock_load.return_value = MagicMock(active=True)
    mock_block.return_value = None
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _result(mappings_one=_active_user(risk_level="critical")),
            _result(one=None),  # open handoff check
            _result(mappings_one={"relationship_stage": "S5", "updated_at": None}),
            _result(),  # insert pending task
        ]
    )
    db.commit = AsyncMock()
    client = TestClient(_app(db))

    r = client.post(
        "/api/v1/notifications/schedule",
        json={
            "user_id": USER_ID,
            "channel": "telegram",
            "notification_type": "s5_care_checkin",
        },
    )

    assert r.status_code == 202, r.text
    assert r.json()["status"] == "pending"
    db.commit.assert_awaited_once()


@patch("services.risk_s5.load_s5_restrictions", new_callable=AsyncMock)
@patch("services.risk_s5.notification_block_reason")
def test_schedule_blocks_silent_reactivation_for_s5(mock_block, mock_load):
    mock_load.return_value = MagicMock(active=True)
    mock_block.return_value = "S5: silent_reactivation notifications are blocked"
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _result(mappings_one=_active_user()),
            _result(one=None),  # open handoff check
            _result(mappings_one={"relationship_stage": "S5", "updated_at": None}),
        ]
    )
    db.commit = AsyncMock()
    client = TestClient(_app(db))

    r = client.post(
        "/api/v1/notifications/schedule",
        json={
            "user_id": USER_ID,
            "channel": "telegram",
            "notification_type": "silent_reactivation",
        },
    )

    assert r.status_code == 409
    assert "S5" in r.json()["detail"]
    db.commit.assert_not_awaited()


def test_send_now_marks_failed_when_bot_token_missing():
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _result(mappings_one=_active_user()),
            _result(one=None),
            _result(mappings_one=None),
            _result(mappings_one={"daily_count": 0, "weekly_count": 0}),
            _result(mappings_one=None),
            _result(),  # insert sending task
            _result(),  # mark failed
        ]
    )
    db.commit = AsyncMock()
    client = TestClient(_app(db))

    with patch("api.notifications.settings.TELEGRAM_BOT_TOKEN", ""):
        r = client.post(
            "/api/v1/notifications/send-now",
            json={
                "user_id": USER_ID,
                "channel": "telegram",
                "notification_type": "silent_reactivation",
            },
        )

    assert r.status_code == 503
    assert r.json()["detail"]["message"] == "Telegram bot token missing"
    sql_text = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)
    assert "failure_reason = :reason" in sql_text
    assert db.commit.await_count >= 2
