from __future__ import annotations

from uuid import uuid4

import importlib
import pytest

from services.mtproto.session_manager import SessionManager


session_manager_module = importlib.import_module("services.mtproto.session_manager")


class FakeAccount:
    def __init__(self, account_id, *, is_active=True):
        self.id = account_id
        self.is_active = is_active
        self.status = "connected"
        self.last_connected_at = None
        self.last_error_at = None
        self.error_message = None


class FakeTelegramAccountManager:
    def __init__(self, *, connect_results=None, account=None):
        self.connect_results = list(connect_results or [])
        self.account = account
        self.status_updates = []
        self.connect_calls = []

    async def _update_account_status(self, account_id, status, reason):
        self.status_updates.append((account_id, status, reason))

    async def get_account(self, account_id):
        return self.account

    async def connect_account(self, account_id):
        self.connect_calls.append(account_id)
        if self.connect_results:
            return self.connect_results.pop(0)
        return False


@pytest.mark.asyncio
async def test_p1_18_disconnect_schedules_reconnect(monkeypatch):
    account_id = uuid4()
    fake_manager = FakeTelegramAccountManager(account=FakeAccount(account_id))
    monkeypatch.setattr(session_manager_module, "telegram_account_manager", fake_manager)

    manager = SessionManager(reconnect_interval=30, max_reconnect_attempts=2)
    monkeypatch.setattr(manager, "_schedule_reconnect", lambda account_id: manager.reconnect_tasks.setdefault(account_id, "scheduled"))

    await manager._handle_disconnect(account_id, "socket closed")

    assert fake_manager.status_updates == [(account_id, "disconnected", "socket closed")]
    assert manager.reconnect_tasks[account_id] == "scheduled"


@pytest.mark.asyncio
async def test_p1_18_reconnect_success_removes_task(monkeypatch):
    account_id = uuid4()
    fake_manager = FakeTelegramAccountManager(connect_results=[True])
    monkeypatch.setattr(session_manager_module, "telegram_account_manager", fake_manager)
    monkeypatch.setattr(session_manager_module.asyncio, "sleep", lambda _delay: _noop())

    manager = SessionManager(reconnect_interval=0, max_reconnect_attempts=2)
    manager._running = True
    manager.reconnect_tasks[account_id] = object()

    await manager._reconnect_with_backoff(account_id)

    assert fake_manager.connect_calls == [account_id]
    assert account_id not in manager.reconnect_tasks


@pytest.mark.asyncio
async def test_p1_18_reconnect_marks_error_after_max_attempts(monkeypatch):
    account_id = uuid4()
    fake_manager = FakeTelegramAccountManager(connect_results=[])
    monkeypatch.setattr(session_manager_module, "telegram_account_manager", fake_manager)

    manager = SessionManager(reconnect_interval=0, max_reconnect_attempts=1)
    manager._running = True
    manager.reconnect_tasks[account_id] = object()

    await manager._reconnect_with_backoff(account_id, attempt=2)

    assert fake_manager.status_updates == [
        (account_id, "error", "Max reconnect attempts (1) reached")
    ]
    assert account_id not in manager.reconnect_tasks


async def _noop():
    return None
