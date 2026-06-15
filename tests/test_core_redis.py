"""Tests for shared Redis helper."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_get_redis_lazy_initializes_client(monkeypatch):
    import core.redis as redis_mod

    redis_mod._redis_client = None
    created: dict[str, object] = {}

    class FakeRedis:
        pass

    def fake_from_url(url, **kwargs):
        created["url"] = url
        created["kwargs"] = kwargs
        return FakeRedis()

    monkeypatch.setattr(redis_mod.aioredis, "from_url", fake_from_url)
    monkeypatch.setattr(redis_mod.settings, "REDIS_URL", "redis://test:6379/0")

    client = await redis_mod.get_redis()
    again = await redis_mod.get_redis()

    assert isinstance(client, FakeRedis)
    assert client is again
    assert created["url"] == "redis://test:6379/0"
