from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from services.telegram_session_login import TelegramSessionLoginManager


@pytest.mark.asyncio
async def test_start_login_uses_and_remembers_selected_credential():
    credential_id = uuid4()
    client = AsyncMock()
    client.send_code_request.return_value.phone_code_hash = "code-hash"

    with patch("services.telegram_session_login.TelegramClient", return_value=client):
        manager = TelegramSessionLoginManager()
        manager._ensure_configured = lambda: None
        manager._resolve_api_credentials = AsyncMock(
            return_value=(credential_id, 2040, "selected-api-hash")
        )
        result = await manager.start_login(
            "+15550001111", api_credential_id=credential_id
        )

    manager._resolve_api_credentials.assert_awaited_once_with(credential_id)
    assert manager.pending[result["login_id"]].api_credential_id == credential_id


def test_credential_count_excludes_inactive_and_banned_accounts():
    import inspect
    from api.telegram_accounts import list_telegram_api_credentials

    source = inspect.getsource(list_telegram_api_credentials)
    assert "a.is_active=TRUE AND a.status <> 'banned'" in source
