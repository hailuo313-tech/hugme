"""AccountPool routing and outbound delivery for MTProto real-user accounts."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any, Awaitable, Callable, Optional, Sequence

from services.mtproto.account_routing import assign_account_id, route_redis_key
from services.mtproto.human_like_send import (
    DEFAULT_HUMAN_LIKE_SEND_POLICY,
    ClockFn,
    HumanLikeSendPolicy,
    SleepFn,
    send_human_like_message,
)

ClientResolver = Callable[[str], Awaitable[Any]]


@dataclass(frozen=True)
class AccountRoute:
    """Resolved user-to-account binding."""

    user_id: str
    account_id: str
    redis_key: str
    source: str


@dataclass(frozen=True)
class AccountPoolSendResult:
    """Outbound send result with the selected MTProto account."""

    account_id: str
    user_id: str
    peer: Any
    message: Any


def _decode_redis_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8")
    text = str(value)
    return text if text else None


class AccountPool:
    """Stable user hash routing plus MTProto send_message dispatch."""

    def __init__(
        self,
        *,
        account_ids: Sequence[str],
        client_resolver: ClientResolver,
        redis: Any | None = None,
        route_ttl_seconds: int | None = None,
        send_policy: HumanLikeSendPolicy = DEFAULT_HUMAN_LIKE_SEND_POLICY,
    ) -> None:
        self.account_ids = tuple(str(account_id) for account_id in account_ids if str(account_id))
        if not self.account_ids:
            raise ValueError("account_ids must not be empty")
        self.client_resolver = client_resolver
        self.redis = redis
        self.route_ttl_seconds = route_ttl_seconds
        self.send_policy = send_policy
        self._last_sent_at_by_account: dict[str, float] = {}

    async def resolve_account(self, user_id: str | int) -> AccountRoute:
        user_key = str(user_id)
        if not user_key:
            raise ValueError("user_id is required")

        redis_key = route_redis_key(user_key)
        cached = await self._get_cached_route(redis_key)
        if cached in self.account_ids:
            return AccountRoute(user_id=user_key, account_id=cached, redis_key=redis_key, source="redis")

        account_id = assign_account_id(user_key, self.account_ids)
        await self._store_route(redis_key, account_id)
        return AccountRoute(user_id=user_key, account_id=account_id, redis_key=redis_key, source="hash")

    async def send_message(
        self,
        *,
        user_id: str | int,
        peer: Any,
        text: str,
        sleep: SleepFn,
        now: ClockFn = monotonic,
        **send_kwargs: Any,
    ) -> AccountPoolSendResult:
        route = await self.resolve_account(user_id)
        client = await self.client_resolver(route.account_id)
        if client is None:
            raise LookupError(f"no connected MTProto client for account_id={route.account_id}")

        message = await send_human_like_message(
            client,
            peer,
            text,
            policy=self.send_policy,
            last_sent_at=self._last_sent_at_by_account.get(route.account_id),
            sleep=sleep,
            now=now,
            **send_kwargs,
        )
        self._last_sent_at_by_account[route.account_id] = now()
        return AccountPoolSendResult(
            account_id=route.account_id,
            user_id=route.user_id,
            peer=peer,
            message=message,
        )

    async def _get_cached_route(self, redis_key: str) -> Optional[str]:
        if self.redis is None:
            return None
        return _decode_redis_value(await self.redis.get(redis_key))

    async def _store_route(self, redis_key: str, account_id: str) -> None:
        if self.redis is None:
            return
        if self.route_ttl_seconds is None:
            await self.redis.set(redis_key, account_id)
        else:
            await self.redis.set(redis_key, account_id, ex=self.route_ttl_seconds)
