from types import SimpleNamespace

import pytest

from services.mtproto.auto_reply import _mark_read_after_delay


class _ReadClient:
    def __init__(self):
        self.calls = []

    async def send_read_acknowledge(self, peer, message=None):
        self.calls.append((peer, message))


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
async def test_mtproto_read_ack_waits_four_seconds_before_marking_read():
    client = _ReadClient()
    event = SimpleNamespace(chat_id=12345)
    message = SimpleNamespace(id=99)
    log = _Log()
    delays = []

    async def _sleep(seconds):
        delays.append(seconds)

    await _mark_read_after_delay(client, event, message, log, sleep=_sleep)

    assert delays == [4.0]
    assert client.calls == [(12345, message)]
    assert ("info", "mtproto.inbound.mark_read") in log.events
