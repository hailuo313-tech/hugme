from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from telethon.errors import SessionPasswordNeededError

from api.admin import require_operator
from api.telegram_accounts import router
from services.telegram_session_login import (
    TelegramSessionLoginError,
    TelegramSessionLoginManager,
    TelegramSessionPasswordRequired,
)


class FakeSession:
    def save(self) -> str:
        return "generated_string_session"


class FakeClient:
    def __init__(self):
        self.session = FakeSession()
        self.connect = AsyncMock()
        self.disconnect = AsyncMock()
        self.send_code_request = AsyncMock(
            return_value=SimpleNamespace(phone_code_hash="hash_123")
        )
        self.sign_in = AsyncMock()
        self.is_user_authorized = AsyncMock(return_value=True)
        self.get_me = AsyncMock(
            return_value=SimpleNamespace(id=777, username="tg_user", first_name="Alice")
        )


@pytest.fixture
def configured_settings():
    with patch("services.telegram_session_login.settings") as mock_settings:
        mock_settings.TELEGRAM_API_ID = 12345
        mock_settings.TELEGRAM_API_HASH = "api_hash"
        mock_settings.TELEGRAM_SESSION_FERNET_KEY = "fernet"
        mock_settings.TELEGRAM_DEVICE_MODEL = "ERIS"
        mock_settings.TELEGRAM_SYSTEM_VERSION = "1.0"
        yield mock_settings


@pytest.mark.asyncio
async def test_start_login_sends_code_and_keeps_pending(configured_settings):
    fake_client = FakeClient()

    with patch("services.telegram_session_login.TelegramClient", return_value=fake_client):
        manager = TelegramSessionLoginManager(ttl_seconds=60)
        result = await manager.start_login("+1234567890", display_name="TG 01")

    assert result["login_id"] in manager.pending
    assert result["phone"] == "+1234567890"
    fake_client.connect.assert_awaited_once()
    fake_client.send_code_request.assert_awaited_once_with("+1234567890")


@pytest.mark.asyncio
async def test_verify_login_saves_generated_session(configured_settings):
    fake_client = FakeClient()
    account_id = uuid4()

    with patch("services.telegram_session_login.TelegramClient", return_value=fake_client), \
         patch("services.telegram_session_login.telegram_account_manager") as account_manager:
        account_manager.add_account = AsyncMock(return_value=account_id)
        account_manager.connect_account = AsyncMock(return_value=False)

        manager = TelegramSessionLoginManager(ttl_seconds=60)
        started = await manager.start_login("+1234567890", display_name="TG 01")
        result = await manager.verify_login(started["login_id"], code="12345")

    fake_client.sign_in.assert_awaited_once_with(
        phone="+1234567890",
        code="12345",
        phone_code_hash="hash_123",
    )
    account_manager.add_account.assert_awaited_once()
    kwargs = account_manager.add_account.await_args.kwargs
    assert kwargs["session_string"] == "generated_string_session"
    assert kwargs["display_name"] == "TG 01"
    assert result["account_id"] == str(account_id)
    assert result["username"] == "tg_user"
    assert started["login_id"] not in manager.pending
    fake_client.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_verify_login_requires_2fa_password(configured_settings):
    fake_client = FakeClient()
    fake_client.sign_in.side_effect = SessionPasswordNeededError(request=None)

    with patch("services.telegram_session_login.TelegramClient", return_value=fake_client):
        manager = TelegramSessionLoginManager(ttl_seconds=60)
        started = await manager.start_login("+1234567890")

        with pytest.raises(TelegramSessionPasswordRequired):
            await manager.verify_login(started["login_id"], code="12345")


@pytest.mark.asyncio
async def test_start_login_requires_mtproto_config():
    with patch("services.telegram_session_login.settings") as mock_settings:
        mock_settings.TELEGRAM_API_ID = None
        mock_settings.TELEGRAM_API_HASH = None
        mock_settings.TELEGRAM_SESSION_FERNET_KEY = None
        manager = TelegramSessionLoginManager()

        with pytest.raises(TelegramSessionLoginError):
            await manager.start_login("+1234567890")


def _api_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)

    async def _fake_operator() -> dict:
        return {"sub": "op-test", "type": "operator", "role": "admin"}

    app.dependency_overrides[require_operator] = _fake_operator
    return TestClient(app)


def test_start_session_login_api_requires_operator_token():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/telegram/session-login/start",
        json={"phone": "+1234567890"},
    )

    assert resp.status_code == 401


def test_start_session_login_api_returns_login_id():
    client = _api_client()

    with patch("api.telegram_accounts.telegram_session_login_manager") as manager:
        manager.start_login = AsyncMock(
            return_value={
                "login_id": "login-1",
                "phone": "+1234567890",
                "expires_at": "2026-05-21T00:00:00",
            }
        )

        resp = client.post(
            "/api/v1/telegram/session-login/start",
            json={"phone": "+1234567890", "display_name": "TG 01"},
        )

    assert resp.status_code == 200
    assert resp.json()["login_id"] == "login-1"
    manager.start_login.assert_awaited_once_with(
        phone="+1234567890",
        display_name="TG 01",
    )


def test_verify_session_login_api_reports_2fa_required():
    client = _api_client()

    with patch("api.telegram_accounts.telegram_session_login_manager") as manager:
        manager.verify_login = AsyncMock(side_effect=TelegramSessionPasswordRequired())

        resp = client.post(
            "/api/v1/telegram/session-login/verify",
            json={"login_id": "login-1", "code": "12345"},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "password_required"
    assert resp.json()["requires_password"] is True
