"""Stable user to account routing (C-15)."""
from __future__ import annotations
import hashlib
from typing import Sequence

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
