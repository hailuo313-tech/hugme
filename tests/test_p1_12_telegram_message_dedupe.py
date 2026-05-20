from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services.mtproto.newmessage_inbound import enqueue_new_message


class FakeRedis:
    def __init__(self) -> None:
        self.keys: dict[str, str] = {}
        self.xadd_calls: list[tuple[str, dict[str, str], int]] = []
        self.set_calls: list[tuple[str, int | None, bool | None]] = []

    async def set(self, key: str, value: str, *, ex: int | None = None, nx: bool | None = None) -> bool:
        self.set_calls.append((key, ex, nx))
        if nx and key in self.keys:
            return False
        self.keys[key] = value
        return True

    async def xadd(self, stream: str, fields: dict[str, str], maxlen: int) -> str:
        self.xadd_calls.append((stream, fields, maxlen))
        return f"stream-id-{len(self.xadd_calls)}"


class FakeNewMessageEvent:
    def __init__(self, *, sender_id: int = 99, message_id: int = 42, text: str = "hello") -> None:
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
        return None


@pytest.mark.asyncio
async def test_same_user_and_message_id_is_enqueued_once() -> None:
    redis = FakeRedis()

    first_id, _ = await enqueue_new_message(redis, FakeNewMessageEvent(), account_id="tg-acc-01")
    second_id, _ = await enqueue_new_message(redis, FakeNewMessageEvent(), account_id="tg-acc-01")

    assert first_id == "stream-id-1"
    assert second_id is None
    assert len(redis.xadd_calls) == 1
    assert redis.set_calls == [
        ("telegram_msg:tg_99:42", 3600, True),
        ("telegram_msg:tg_99:42", 3600, True),
    ]


@pytest.mark.asyncio
async def test_different_message_id_is_not_treated_as_duplicate() -> None:
    redis = FakeRedis()

    first_id, _ = await enqueue_new_message(redis, FakeNewMessageEvent(message_id=42), account_id="tg-acc-01")
    second_id, _ = await enqueue_new_message(redis, FakeNewMessageEvent(message_id=43), account_id="tg-acc-01")

    assert first_id == "stream-id-1"
    assert second_id == "stream-id-2"
    assert len(redis.xadd_calls) == 2


@pytest.mark.asyncio
async def test_different_user_same_message_id_is_not_treated_as_duplicate() -> None:
    redis = FakeRedis()

    first_id, _ = await enqueue_new_message(redis, FakeNewMessageEvent(sender_id=99), account_id="tg-acc-01")
    second_id, _ = await enqueue_new_message(redis, FakeNewMessageEvent(sender_id=100), account_id="tg-acc-01")

    assert first_id == "stream-id-1"
    assert second_id == "stream-id-2"
    assert len(redis.xadd_calls) == 2
