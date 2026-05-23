"""Unit tests for P1-09 Telegram accounts multi-account management."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.models.telegram_accounts import TelegramAccount
from app.services.telegram_account_manager import TelegramAccountManager


def _mock_session_context(mock_session):
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=mock_session)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


@pytest.fixture
def mock_fernet():
    """Mock Fernet encryption."""
    with patch("app.services.telegram_account_manager.Fernet") as mock:
        mock_instance = MagicMock()
        mock_instance.encrypt.return_value = b"encrypted_session"
        mock_instance.decrypt.return_value = b"decrypted_session"
        mock.return_value = mock_instance
        yield mock_instance


def test_telegram_account_generates_id_on_init():
    """Model instances always have a primary key before SQLAlchemy flushes."""
    account = TelegramAccount(
        phone="+1234567890",
        session_string="encrypted_session",
    )

    assert account.id is not None


@pytest.fixture
def account_manager(mock_fernet):
    """Create TelegramAccountManager instance."""
    with patch("app.services.telegram_account_manager.settings") as mock_settings:
        mock_settings.TELEGRAM_SESSION_FERNET_KEY = "test_fernet_key_for_testing_only"
        mock_settings.TELEGRAM_API_ID = 12345
        mock_settings.TELEGRAM_API_HASH = "test_api_hash"
        mock_settings.TELEGRAM_DEVICE_MODEL = "ERIS"
        mock_settings.TELEGRAM_SYSTEM_VERSION = "1.0"
        return TelegramAccountManager()


@pytest.mark.asyncio
async def test_encrypt_decrypt_session(account_manager):
    """Test session encryption and decryption."""
    original_session = "test_session_string"
    encrypted = account_manager._encrypt_session(original_session)
    decrypted = account_manager._decrypt_session(encrypted)

    assert encrypted != original_session
    assert decrypted == original_session


@pytest.mark.asyncio
async def test_add_account(account_manager):
    """Test adding a new Telegram account."""
    with patch("app.services.telegram_account_manager.AsyncSessionLocal") as mock_session_factory:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()
        mock_session_factory.return_value = _mock_session_context(mock_session)

        # Mock the account object
        mock_account = MagicMock()
        mock_account.id = uuid4()
        mock_session.refresh.side_effect = lambda obj: setattr(obj, "id", mock_account.id)

        account_id = await account_manager.add_account(
            phone="+1234567890",
            session_string="test_session",
            is_bot=False,
            display_name="Test Account",
        )

        assert account_id is not None
        mock_session.add.assert_called_once()
        added_account = mock_session.add.call_args.args[0]
        assert added_account.id is not None
        mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_upsert_account_creates_id_before_commit(account_manager):
    """Test upsert creates new accounts with an explicit UUID primary key."""
    with patch("app.services.telegram_account_manager.AsyncSessionLocal") as mock_session_factory:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()
        mock_session_factory.return_value = _mock_session_context(mock_session)

        account_id = await account_manager.upsert_account(
            phone="+1234567890",
            session_string="test_session",
            is_bot=False,
            display_name="Test Account",
        )

        assert account_id is not None
        mock_session.add.assert_called_once()
        added_account = mock_session.add.call_args.args[0]
        assert added_account.id == account_id
        mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_account_status(account_manager):
    """Test getting account status."""
    account_id = uuid4()

    with patch.object(account_manager, "get_account", new=AsyncMock()) as mock_get_account:
        mock_account = TelegramAccount(
            id=account_id,
            phone="+1234567890",
            session_string="encrypted_session",
            status="connected",
            is_active=True,
            display_name="Test Account",
            username="testuser",
            user_id=123456789,
        )
        mock_get_account.return_value = mock_account

        status = await account_manager.get_account_status(account_id)

        assert status is not None
        assert status["id"] == str(account_id)
        assert status["phone"] == "+1234567890"
        assert status["status"] == "connected"
        assert status["is_connected"] is False  # Not in clients dict


@pytest.mark.asyncio
async def test_connect_account_success(account_manager):
    """Test successful account connection."""
    account_id = uuid4()

    with patch.object(account_manager, "get_account", new=AsyncMock()) as mock_get_account, \
         patch.object(account_manager, "_update_account_status", new=AsyncMock()) as mock_update_status, \
         patch("app.services.telegram_account_manager.AsyncSessionLocal") as mock_session_factory, \
         patch("app.services.telegram_account_manager.TelegramClient") as mock_client_class:

        # Mock database session
        mock_session = AsyncMock()
        mock_account = TelegramAccount(
            id=account_id,
            phone="+1234567890",
            session_string="encrypted_session",
            status="disconnected",
            is_active=True,
        )
        mock_get_account.return_value = mock_account
        mock_session.get = AsyncMock(return_value=mock_account)
        mock_session.commit = AsyncMock()
        mock_session_factory.return_value = _mock_session_context(mock_session)

        # Mock Telegram client
        mock_client = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.is_user_authorized = AsyncMock(return_value=True)
        mock_client.get_me = AsyncMock(return_value=MagicMock(
            first_name="Test",
            username="testuser",
            id=123456789,
        ))
        mock_client.add_event_handler = MagicMock()
        mock_client.remove_event_handler = MagicMock()
        mock_client_class.return_value = mock_client

        success = await account_manager.connect_account(account_id)

        assert success is True
        mock_client.connect.assert_called_once()
        assert mock_update_status.await_count >= 1
        assert account_id in account_manager.clients


@pytest.mark.asyncio
async def test_connect_account_not_authorized(account_manager):
    """Test account connection when session is not authorized."""
    account_id = uuid4()

    with patch.object(account_manager, "get_account", new=AsyncMock()) as mock_get_account, \
         patch.object(account_manager, "_update_account_status", new=AsyncMock()) as mock_update_status, \
         patch("app.services.telegram_account_manager.TelegramClient") as mock_client_class:

        mock_account = TelegramAccount(
            id=account_id,
            phone="+1234567890",
            session_string="encrypted_session",
            status="disconnected",
            is_active=True,
        )
        mock_get_account.return_value = mock_account

        # Mock Telegram client
        mock_client = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.is_user_authorized = AsyncMock(return_value=False)
        mock_client.disconnect = AsyncMock()
        mock_client_class.return_value = mock_client

        success = await account_manager.connect_account(account_id)

        assert success is False
        mock_client.disconnect.assert_called_once()
        assert mock_update_status.await_count >= 2
        assert account_id not in account_manager.clients


@pytest.mark.asyncio
async def test_disconnect_account(account_manager):
    """Test disconnecting an account."""
    account_id = uuid4()

    # Add a mock client
    mock_client = AsyncMock()
    mock_client.disconnect = AsyncMock()
    account_manager.clients[account_id] = mock_client

    with patch.object(account_manager, "_update_account_status", new=AsyncMock()) as mock_update_status:
        success = await account_manager.disconnect_account(account_id)

        assert success is True
        mock_client.disconnect.assert_called_once()
        mock_update_status.assert_awaited_once_with(account_id, "disconnected")
        assert account_id not in account_manager.clients


@pytest.mark.asyncio
async def test_get_any_connected_client(account_manager):
    """Test getting any connected client."""
    # No clients
    client = await account_manager.get_any_connected_client()
    assert client is None

    # Add a client
    account_id = uuid4()
    mock_client = AsyncMock()
    account_manager.clients[account_id] = mock_client

    client = await account_manager.get_any_connected_client()
    assert client is not None
    assert client == mock_client


@pytest.mark.asyncio
async def test_get_all_accounts_status(account_manager):
    """Test getting all accounts status."""
    with patch.object(account_manager, "get_active_accounts", new=AsyncMock()) as mock_get_active_accounts:
        account1 = TelegramAccount(
            id=uuid4(),
            phone="+1234567890",
            session_string="encrypted_session",
            status="connected",
            is_active=True,
        )
        account2 = TelegramAccount(
            id=uuid4(),
            phone="+0987654321",
            session_string="encrypted_session2",
            status="disconnected",
            is_active=True,
        )
        mock_get_active_accounts.return_value = [account1, account2]

        statuses = await account_manager.get_all_accounts_status()

        assert len(statuses) == 2
        assert statuses[0]["status"] == "connected"
        assert statuses[1]["status"] == "disconnected"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
