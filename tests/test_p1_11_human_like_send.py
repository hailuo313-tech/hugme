from __future__ import annotations

import pytest

from services.mtproto.human_like_send import (
    HumanLikeSendPolicy,
    human_typing_delay_seconds,
    send_human_like_message,
    send_typing,
    wait_for_inter_message_gap,
)


class FakeTypingAction:
    def __init__(self, client: "FakeTelethonClient", peer: str, action: str) -> None:
        self.client = client
        self.peer = peer
        self.action = action

    async def __aenter__(self) -> None:
        self.client.events.append(("typing.start", self.peer, self.action))

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.client.events.append(("typing.stop", self.peer, self.action))


class FakeTelethonClient:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def action(self, peer: str, action: str) -> FakeTypingAction:
        self.events.append(("action", peer, action))
        return FakeTypingAction(self, peer, action)

    async def send_message(self, peer: str, text: str, **kwargs):
        self.events.append(("send_message", peer, text, kwargs))
        return {"id": 123, "peer": peer, "text": text}


class FakeSleeper:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("hi", 4.0),
        ("hello, this is a medium text", 7.0),
        ("x" * 50, 11.0),
        ("x" * 51, 18.0),
    ],
)
def test_human_typing_delay_seconds_uses_text_length_buckets(text: str, expected: float) -> None:
    assert human_typing_delay_seconds(text) == expected


@pytest.mark.asyncio
async def test_send_typing_shows_telethon_typing_action() -> None:
    client = FakeTelethonClient()
    sleeper = FakeSleeper()

    await send_typing(client, "tg_99", sleep=sleeper)

    assert sleeper.delays == [2.0]
    assert client.events == [
        ("action", "tg_99", "typing"),
        ("typing.start", "tg_99", "typing"),
        ("typing.stop", "tg_99", "typing"),
    ]


@pytest.mark.asyncio
async def test_send_human_like_message_types_waits_then_sends() -> None:
    client = FakeTelethonClient()
    sleeper = FakeSleeper()

    result = await send_human_like_message(
        client,
        "tg_99",
        "hello from account pool",
        sleep=sleeper,
        parse_mode="html",
    )

    assert result["id"] == 123
    assert sleeper.delays == [7.0]
    assert client.events == [
        ("action", "tg_99", "typing"),
        ("typing.start", "tg_99", "typing"),
        ("typing.stop", "tg_99", "typing"),
        ("send_message", "tg_99", "hello from account pool", {"parse_mode": "html"}),
    ]


@pytest.mark.asyncio
async def test_send_human_like_message_enforces_inter_message_gap_before_typing() -> None:
    client = FakeTelethonClient()
    sleeper = FakeSleeper()
    policy = HumanLikeSendPolicy(minimum_inter_message_seconds=8.0)

    await send_human_like_message(
        client,
        "tg_99",
        "hi",
        policy=policy,
        last_sent_at=100.0,
        now=lambda: 103.0,
        sleep=sleeper,
    )

    assert sleeper.delays == [5.0, 4.0]
    assert client.events[0] == ("action", "tg_99", "typing")


@pytest.mark.asyncio
async def test_wait_for_inter_message_gap_noops_without_last_send() -> None:
    sleeper = FakeSleeper()

    await wait_for_inter_message_gap(last_sent_at=None, sleep=sleeper)

    assert sleeper.delays == []
