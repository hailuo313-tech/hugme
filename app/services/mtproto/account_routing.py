"""Stable user to account routing (C-15)."""
from __future__ import annotations
import hashlib
from typing import Any, Sequence

ROUTE_KEY_PREFIX = "mtproto:route:"
ACCOUNT_KEY_PREFIX = "mtproto:acct:"

def route_redis_key(user_id: str | int) -> str:
    return f"{ROUTE_KEY_PREFIX}{user_id}"

def account_redis_prefix(account_id: str) -> str:
    return f"{ACCOUNT_KEY_PREFIX}{account_id}:"

def account_index_for_user(user_id: str | int, pool_size: int) -> int:
    if pool_size < 1:
        raise ValueError("pool_size must be >= 1")
    digest = hashlib.sha256(str(user_id).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % pool_size

def assign_account_id(user_id: str | int, account_ids: Sequence[str]) -> str:
    if not account_ids:
        raise ValueError("account_ids must not be empty")
    return account_ids[account_index_for_user(user_id, len(account_ids))]


async def pin_mtproto_account_route(
    redis: Any,
    *,
    user_id: str | int,
    account_id: str,
    ttl_seconds: int | None = 86400,
) -> None:
    """Pin a user to the MTProto account that already owns the live dialog."""
    if redis is None:
        return
    account_key = str(account_id or "").strip()
    if not account_key:
        return
    redis_key = route_redis_key(user_id)
    if ttl_seconds is None:
        await redis.set(redis_key, account_key)
    else:
        await redis.set(redis_key, account_key, ex=ttl_seconds)
