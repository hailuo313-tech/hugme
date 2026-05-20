from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services.mtproto.newmessage_inbound import (
    INBOUND_QUEUE_STREAM,
    TELEGRAM_MESSAGE_DEDUPE_TTL_SECONDS,
    claim_telegram_message_once,
    enqueue_new_message,
    telegram_message_dedupe_key,
)


class FakeRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str], int]] = []
        self.keys: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, int | None, bool | None]] = []

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        nx: bool | None = None,
    ) -> bool:
        self.set_calls.append((key, value, ex, nx))
        if nx and key in self.keys:
            return False
        self.keys[key] = value
        return True

    async def xadd(self, stream: str, fields: dict[str, str], maxlen: int) -> str:
        self.calls.append((stream, fields, maxlen))
        return "1700000000000-0"


class FakeNewMessageEvent:
    def __init__(self, message: SimpleNamespace, sender: SimpleNamespace | None = None) -> None:
        self.message = message
        self.sender_id = message.sender_id
        self.chat_id = message.chat_id
        self.original_update = f"update:{message.id}"
        self._sender = sender

    async def get_sender(self) -> SimpleNamespace | None:
        return self._sender


def _message(**overrides) -> SimpleNamespace:
    base = {
        "id": 42,
        "sender_id": 99,
        "chat_id": -100123,
        "date": datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc),
        "raw_text": "",
        "text": "",
        "message": "",
        "photo": None,
        "voice": None,
        "audio": None,
        "document": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


async def _enqueue(message: SimpleNamespace, sender: SimpleNamespace | None = None) -> dict[str, str]:
    redis = FakeRedis()
    queue_id, envelope = await enqueue_new_message(
        redis,
        FakeNewMessageEvent(message, sender=sender),
        account_id="tg-acc-01",
    )

    assert queue_id == "1700000000000-0"
    assert envelope.platform == "telegram_real_user"
    assert len(redis.calls) == 1
    stream, fields, maxlen = redis.calls[0]
    assert stream == INBOUND_QUEUE_STREAM
    assert maxlen == 100_000
    assert fields["platform"] == "telegram_real_user"
    assert fields["account_id"] == "tg-acc-01"
    assert fields["external_user_id"] == "tg_99"
    assert redis.set_calls == [
        ("telegram_msg:tg_99:42", "1", TELEGRAM_MESSAGE_DEDUPE_TTL_SECONDS, True)
    ]
    metadata = json.loads(fields["metadata"])
    assert metadata["telegram_message_id"] == "42"
    assert metadata["telegram_chat_id"] == "-100123"
    assert metadata["idempotency_key"] == "tg-acc-01:-100123:42"
    return fields


@pytest.mark.asyncio
async def test_text_newmessage_enqueues_standard_envelope():
    fields = await _enqueue(
        _message(raw_text="hello from real user"),
        sender=SimpleNamespace(phone="15551234567"),
    )

    assert fields["message_type"] == "text"
    assert fields["content"] == "hello from real user"
    assert fields["sender_phone"] == "+15551234567"


@pytest.mark.asyncio
async def test_photo_newmessage_enqueues_image_envelope():
    fields = await _enqueue(_message(photo=object(), message="caption text"))

    assert fields["message_type"] == "image"
    assert fields["content"] == "caption text"
    assert json.loads(fields["metadata"])["media_kind"] == "image"


@pytest.mark.asyncio
async def test_voice_newmessage_enqueues_voice_envelope():
    document = SimpleNamespace(mime_type="audio/ogg")
    fields = await _enqueue(_message(document=document, message=""))

    assert fields["message_type"] == "voice"
    assert fields["content"] == "[voice]"
    assert json.loads(fields["metadata"])["media_kind"] == "voice"


def test_telegram_message_dedupe_key_matches_contract():
    assert telegram_message_dedupe_key("tg_99", "42") == "telegram_msg:tg_99:42"


@pytest.mark.asyncio
async def test_claim_telegram_message_once_uses_one_hour_ttl():
    redis = FakeRedis()

    first = await claim_telegram_message_once(redis, user_id="tg_99", message_id="42")
    second = await claim_telegram_message_once(redis, user_id="tg_99", message_id="42")

    assert first is True
    assert second is False
    assert redis.set_calls == [
        ("telegram_msg:tg_99:42", "1", 3600, True),
        ("telegram_msg:tg_99:42", "1", 3600, True),
    ]


@pytest.mark.asyncio
async def test_duplicate_newmessage_does_not_enqueue_again():
    redis = FakeRedis()
    message = _message(raw_text="duplicate")

    first_id, first_env = await enqueue_new_message(
        redis,
        FakeNewMessageEvent(message),
        account_id="tg-acc-01",
    )
    second_id, second_env = await enqueue_new_message(
        redis,
        FakeNewMessageEvent(message),
        account_id="tg-acc-01",
    )

    assert first_id == "1700000000000-0"
    assert second_id is None
    assert first_env.metadata.telegram_message_id == second_env.metadata.telegram_message_id == "42"
    assert len(redis.calls) == 1
