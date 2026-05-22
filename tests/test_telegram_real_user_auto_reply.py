from types import SimpleNamespace

import pytest

from services.telegram_real_user_auto_reply import _is_managed_telegram_account, _mark_read


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Db:
    def __init__(self, row):
        self.row = row
        self.params = None

    async def execute(self, _statement, params=None):
        self.params = params or {}
        return _Result(self.row)


@pytest.mark.asyncio
async def test_managed_telegram_account_sender_is_skipped():
    db = _Db(SimpleNamespace(found=True))

    assert await _is_managed_telegram_account(db, "tg_7518020047") is True
    assert db.params["telegram_user_id"] == 7518020047


@pytest.mark.asyncio
async def test_unmanaged_telegram_sender_is_not_skipped():
    assert await _is_managed_telegram_account(_Db(None), "tg_7058432267") is False
    assert await _is_managed_telegram_account(_Db(SimpleNamespace()), "web_7058432267") is False
    assert await _is_managed_telegram_account(_Db(SimpleNamespace()), "tg_not_numeric") is False


class _ReadClient:
    def __init__(self):
        self.calls = []

    async def send_read_acknowledge(self, peer, message=None, max_id=None):
        self.calls.append((peer, message, max_id))


class _MarkReadEvent:
    def __init__(self):
        self.marked = False

    async def mark_read(self):
        self.marked = True


class _Log:
    def __init__(self):
        self.events = []

    def info(self, event):
        self.events.append(("info", event))

    def warning(self, event):
        self.events.append(("warning", event))

    def bind(self, **kwargs):
        return self


@pytest.mark.asyncio
async def test_mark_read_acknowledges_before_reply_generation():
    client = _ReadClient()
    log = _Log()
    message = SimpleNamespace(id=99)

    await _mark_read(client, SimpleNamespace(message=message), 12345, log)

    assert client.calls == [(12345, message, 99)]
    assert ("info", "mtproto_auto_reply.read_ack") in log.events


@pytest.mark.asyncio
async def test_mark_read_prefers_event_mark_read():
    client = _ReadClient()
    event = _MarkReadEvent()
    log = _Log()

    await _mark_read(client, event, 12345, log)

    assert event.marked is True
    assert client.calls == []
    assert ("info", "mtproto_auto_reply.read_ack") in log.events
