from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services.mtproto.channel_adapter import (
    MtprotoChannelAdapter,
    register_mtproto_newmessage_listener,
)
from services.mtproto.newmessage_inbound import INBOUND_QUEUE_STREAM


class FakeRedis:
    def __init__(self) -> None:
        self.keys: dict[str, str] = {}
        self.xadd_calls: list[tuple[str, dict[str, str], int]] = []

    async def set(self, key: str, value: str, *, ex: int | None = None, nx: bool | None = None) -> bool:
        if nx and key in self.keys:
            return False
        self.keys[key] = value
        return True

    async def xadd(self, stream: str, fields: dict[str, str], maxlen: int) -> str:
        self.xadd_calls.append((stream, fields, maxlen))
        return "stream-1"


class FakeTelethonClient:
    def __init__(self) -> None:
        self.handlers: list[tuple] = []

    def add_event_handler(self, handler, event) -> None:
        self.handlers.append((handler, event))


class FakeNewMessageFactory:
    def __call__(self, **kwargs):
        return ("NewMessage", kwargs)


class FakeNewMessageEvent:
    def __init__(self, *, message_id: int = 42, sender_id: int = 99, text: str = "hello") -> None:
        self.message = SimpleNamespace(
            id=message_id,
            sender_id=sender_id,
            chat_id=-100123,
            date=datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc),
            raw_text=text,
            text=text,
            message=text,
            photo=None,
            voice=None,
            audio=None,
            document=None,
        )
        self.sender_id = sender_id
        self.chat_id = self.message.chat_id
        self.original_update = f"update:{message_id}"

    async def get_sender(self):
        return SimpleNamespace(phone="15551234567")


@pytest.mark.asyncio
async def test_channel_adapter_normalizes_mtproto_to_standard_inbound_envelope() -> None:
    adapter = MtprotoChannelAdapter(account_id="tg-acc-01", redis=FakeRedis())

    envelope = await adapter.normalize(FakeNewMessageEvent(text="hello adapter"))

    assert adapter.platform == "telegram_real_user"
    assert envelope.platform == "telegram_real_user"
    assert envelope.account_id == "tg-acc-01"
    assert envelope.external_user_id == "tg_99"
    assert envelope.message_type == "text"
    assert envelope.content == "hello adapter"
    assert envelope.metadata.telegram_message_id == "42"
    assert envelope.metadata.telegram_chat_id == "-100123"
    assert envelope.sender_phone == "+15551234567"


@pytest.mark.asyncio
async def test_registered_newmessage_handler_enqueues_standard_fields() -> None:
    redis = FakeRedis()
    client = FakeTelethonClient()

    handler = register_mtproto_newmessage_listener(
        client,
        redis,
        account_id="tg-acc-01",
        event_factory=FakeNewMessageFactory(),
    )
    result = await handler(FakeNewMessageEvent(text="queued"))

    assert client.handlers == [(handler, ("NewMessage", {"incoming": True}))]
    assert result.enqueued is True
    assert result.queue_id == "stream-1"
    assert len(redis.xadd_calls) == 1
    stream, fields, maxlen = redis.xadd_calls[0]
    assert stream == INBOUND_QUEUE_STREAM
    assert maxlen == 100_000
    assert fields["platform"] == "telegram_real_user"
    assert fields["account_id"] == "tg-acc-01"
    assert fields["external_user_id"] == "tg_99"
    assert fields["message_type"] == "text"
    assert fields["content"] == "queued"
    metadata = json.loads(fields["metadata"])
    assert metadata["telegram_message_id"] == "42"
    assert metadata["idempotency_key"] == "tg-acc-01:-100123:42"


@pytest.mark.asyncio
async def test_channel_adapter_skips_duplicate_mtproto_message() -> None:
    redis = FakeRedis()
    adapter = MtprotoChannelAdapter(account_id="tg-acc-01", redis=redis)

    first = await adapter.handle_new_message(FakeNewMessageEvent(message_id=42))
    second = await adapter.handle_new_message(FakeNewMessageEvent(message_id=42))

    assert first.enqueued is True
    assert second.enqueued is False
    assert second.queue_id is None
    assert second.envelope.metadata.telegram_message_id == "42"
    assert len(redis.xadd_calls) == 1
