"""Shared async Redis client for workers and services."""

from __future__ import annotations

from typing import Any

import redis.asyncio as aioredis

from core.config import settings

_redis_client: Any | None = None


async def get_redis():
    """Return a process-wide Redis client (lazy init)."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client
