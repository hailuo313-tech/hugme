"""Unit tests for P1-09 Telegram accounts multi-account management."""

from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from app.models.telegram_accounts import TelegramAccount
from app.services.telegram_account_manager import TelegramAccountManager


@pytest.fixture
def mock_fernet():
    """Mock Fernet encryption."""
    with patch("app.services.telegram_account_manager.Fernet") as mock:
        mock_instance = MagicMock()
        mock_instance.encrypt.return_value = b"encrypted_session"
        mock_instance.decrypt.return_value = b"decrypted_session"
        mock.return_value = mock_instance
        yield mock_instance


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
    with patch("app.services.telegram_account_manager.get_async_session") as mock_session_gen:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        # Mock the account object
        mock_account = MagicMock()
        mock_account.id = uuid4()
        mock_session.refresh.side_effect = lambda obj: setattr(obj, "id", mock_account.id)

        mock_session_gen.__anext__ = AsyncMock(return_value=mock_session)

        account_id = await account_manager.add_account(
            phone="+1234567890",
            session_string="test_session",
            is_bot=False,
            display_name="Test Account",
        )

        assert account_id is not None
        mock_session.add.assert_called_once()
        created_account = mock_session.add.call_args.args[0]
        assert isinstance(created_account.id, UUID)
        assert account_id == created_account.id
        mock_session.commit.assert_called_once()


def test_api_container_defaults_to_single_worker_for_session_login():
    """Telegram session-login state is process-local until it is moved to Redis/DB."""
    dockerfile = (Path(__file__).resolve().parents[1] / "app" / "Dockerfile").read_text(encoding="utf-8")

    assert "${API_WORKERS:-1}" in dockerfile


@pytest.mark.asyncio
async def test_get_account_status(account_manager):
    """Test getting account status."""
    account_id = uuid4()

    with patch("app.services.telegram_account_manager.get_async_session") as mock_session_gen:
        mock_session = AsyncMock()
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
        mock_session.execute = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_account

        mock_session_gen.__anext__ = AsyncMock(return_value=mock_session)

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

    with patch("app.services.telegram_account_manager.get_async_session") as mock_session_gen, \
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
        mock_session.execute = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_account
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        mock_session_gen.__anext__ = AsyncMock(return_value=mock_session)

        # Mock Telegram client
        mock_client = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.is_user_authorized = AsyncMock(return_value=True)
        mock_client.get_me = AsyncMock(return_value=MagicMock(
            first_name="Test",
            username="testuser",
            id=123456789,
        ))
        mock_client_class.return_value = mock_client

        success = await account_manager.connect_account(account_id)

        assert success is True
        mock_client.connect.assert_called_once()
        assert account_id in account_manager.clients


@pytest.mark.asyncio
async def test_connect_account_not_authorized(account_manager):
    """Test account connection when session is not authorized."""
    account_id = uuid4()

    with patch("app.services.telegram_account_manager.get_async_session") as mock_session_gen, \
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
        mock_session.execute = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_account
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        mock_session_gen.__anext__ = AsyncMock(return_value=mock_session)

        # Mock Telegram client
        mock_client = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.is_user_authorized = AsyncMock(return_value=False)
        mock_client.disconnect = AsyncMock()
        mock_client_class.return_value = mock_client

        success = await account_manager.connect_account(account_id)

        assert success is False
        mock_client.disconnect.assert_called_once()
        assert account_id not in account_manager.clients


@pytest.mark.asyncio
async def test_disconnect_account(account_manager):
    """Test disconnecting an account."""
    account_id = uuid4()

    # Add a mock client
    mock_client = AsyncMock()
    mock_client.disconnect = AsyncMock()
    account_manager.clients[account_id] = mock_client

    with patch("app.services.telegram_account_manager.get_async_session") as mock_session_gen:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        mock_session_gen.__anext__ = AsyncMock(return_value=mock_session)

        success = await account_manager.disconnect_account(account_id)

        assert success is True
        mock_client.disconnect.assert_called_once()
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
    with patch("app.services.telegram_account_manager.get_async_session") as mock_session_gen:
        mock_session = AsyncMock()
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
        mock_session.execute = AsyncMock()
        mock_session.execute.return_value.scalars.return_value.all.return_value = [account1, account2]

        mock_session_gen.__anext__ = AsyncMock(return_value=mock_session)

        statuses = await account_manager.get_all_accounts_status()

        assert len(statuses) == 2
        assert statuses[0]["status"] == "connected"
        assert statuses[1]["status"] == "disconnected"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
