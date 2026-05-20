from __future__ import annotations

import pytest

from services.mtproto.account_pool import AccountPool
from services.mtproto.account_routing import assign_account_id, route_redis_key


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.set_calls: list[tuple] = []

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str, *args, **kwargs):
        self.values[key] = value
        self.set_calls.append((key, value, args, kwargs))
        return True


class FakeTypingAction:
    def __init__(self, client: "FakeClient", peer: str, action: str) -> None:
        self.client = client
        self.peer = peer
        self.action = action

    async def __aenter__(self) -> None:
        self.client.events.append(("typing.start", self.peer, self.action))

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.client.events.append(("typing.stop", self.peer, self.action))


class FakeClient:
    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        self.events: list[tuple] = []

    def action(self, peer: str, action: str) -> FakeTypingAction:
        self.events.append(("action", self.account_id, peer, action))
        return FakeTypingAction(self, peer, action)

    async def send_message(self, peer: str, text: str, **kwargs):
        self.events.append(("send_message", self.account_id, peer, text, kwargs))
        return {"account_id": self.account_id, "peer": peer, "text": text}


class FakeSleeper:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def _client_resolver(clients: dict[str, FakeClient]):
    async def resolve(account_id: str):
        return clients.get(account_id)

    return resolve


@pytest.mark.asyncio
async def test_same_user_resolves_same_account_and_caches_route() -> None:
    redis = FakeRedis()
    pool_ids = ["acc-a", "acc-b", "acc-c"]
    pool = AccountPool(account_ids=pool_ids, client_resolver=_client_resolver({}), redis=redis)

    first = await pool.resolve_account("user-42")
    second = await pool.resolve_account("user-42")

    assert first.account_id == assign_account_id("user-42", pool_ids)
    assert second.account_id == first.account_id
    assert first.source == "hash"
    assert second.source == "redis"
    assert redis.values[route_redis_key("user-42")] == first.account_id


@pytest.mark.asyncio
async def test_stale_cached_account_is_reassigned_to_current_pool() -> None:
    redis = FakeRedis()
    redis.values[route_redis_key("user-42")] = "retired-account"
    pool_ids = ["acc-a", "acc-b"]
    pool = AccountPool(account_ids=pool_ids, client_resolver=_client_resolver({}), redis=redis)

    route = await pool.resolve_account("user-42")

    assert route.account_id in pool_ids
    assert route.account_id == assign_account_id("user-42", pool_ids)
    assert route.source == "hash"
    assert redis.values[route_redis_key("user-42")] == route.account_id


@pytest.mark.asyncio
async def test_send_message_uses_stable_account_client() -> None:
    redis = FakeRedis()
    clients = {account_id: FakeClient(account_id) for account_id in ["acc-a", "acc-b", "acc-c"]}
    pool = AccountPool(account_ids=list(clients), client_resolver=_client_resolver(clients), redis=redis)
    sleeper = FakeSleeper()

    first = await pool.send_message(
        user_id="user-42",
        peer="tg_99",
        text="hello from pool",
        sleep=sleeper,
        parse_mode="html",
    )
    second = await pool.send_message(
        user_id="user-42",
        peer="tg_99",
        text="again",
        sleep=sleeper,
    )

    assert first.account_id == second.account_id
    assert first.message["account_id"] == second.message["account_id"]
    selected = clients[first.account_id]
    assert selected.events[0] == ("action", first.account_id, "tg_99", "typing")
    assert selected.events[3] == ("send_message", first.account_id, "tg_99", "hello from pool", {"parse_mode": "html"})
    assert selected.events[7] == ("send_message", first.account_id, "tg_99", "again", {})


@pytest.mark.asyncio
async def test_send_message_fails_when_selected_client_is_not_connected() -> None:
    pool = AccountPool(account_ids=["acc-a"], client_resolver=_client_resolver({}), redis=FakeRedis())

    with pytest.raises(LookupError):
        await pool.send_message(user_id="user-42", peer="tg_99", text="hello", sleep=FakeSleeper())
