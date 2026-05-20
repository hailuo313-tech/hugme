"""D3-4 单元测试：app/services/embedding_worker.py

覆盖：
- 空队列 → no-op，stats 全 0
- 拿到 lock + 一批 → embed 后正确 UPDATE，参数包含 vector 字符串
- 没拿到 advisory lock → 立即返回，不发 embed
- embed 失败 → stats.error 非空，不做任何 UPDATE
- start_scheduler 在 disabled / 无 key 时 no-op
"""

from __future__ import annotations

import importlib
from typing import Any, Optional
from uuid import uuid4

import pytest


@pytest.fixture
def worker_mod():
    import services.embedding_worker as mod  # type: ignore

    importlib.reload(mod)
    return mod


# ─────────────────────────────────────────────────────────────
# Fake DB
# ─────────────────────────────────────────────────────────────


class _FakeResult:
    def __init__(self, scalar_val: Any = None, rows: Optional[list] = None):
        self._scalar = scalar_val
        self._rows = rows or []

    def scalar(self):
        return self._scalar

    def fetchall(self):
        return self._rows


class _FakeSession:
    """模拟 AsyncSession：按 SQL 文本顺序返回预设结果。"""

    def __init__(
        self,
        got_lock: bool = True,
        batch_rows: Optional[list] = None,
    ):
        self.got_lock = got_lock
        self.batch_rows = batch_rows or []
        self.calls: list[tuple[str, dict]] = []
        self.commits: int = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, stmt, params=None):
        sql = str(getattr(stmt, "text", stmt)).strip()
        self.calls.append((sql, params or {}))

        if "pg_try_advisory_lock" in sql:
            return _FakeResult(scalar_val=self.got_lock)
        if "pg_advisory_unlock" in sql:
            return _FakeResult(scalar_val=True)
        if "FROM memories" in sql and "embedding IS NULL" in sql:
            return _FakeResult(rows=self.batch_rows)
        if sql.startswith("UPDATE memories"):
            return _FakeResult()
        return _FakeResult()

    async def commit(self):
        self.commits += 1


def _patch_session(monkeypatch, worker_mod, session: _FakeSession):
    def _factory():
        return session

    monkeypatch.setattr(worker_mod, "AsyncSessionLocal", _factory)


# ─────────────────────────────────────────────────────────────
# tick: 空队列
# ─────────────────────────────────────────────────────────────


class TestTickEmpty:
    @pytest.mark.asyncio
    async def test_empty_queue_noop(self, worker_mod, monkeypatch):
        sess = _FakeSession(got_lock=True, batch_rows=[])
        _patch_session(monkeypatch, worker_mod, sess)

        async def _fake_embed(texts, trace_id):
            raise AssertionError("should not be called on empty queue")

        monkeypatch.setattr(worker_mod, "embed", _fake_embed)

        stats = await worker_mod.run_one_tick(trace_id="t")
        assert stats == {"selected": 0, "embedded": 0, "updated": 0, "error": None}
        # 只调了 lock / select / unlock
        sql_texts = [c[0] for c in sess.calls]
        assert any("pg_try_advisory_lock" in s for s in sql_texts)
        assert any("FROM memories" in s for s in sql_texts)
        assert any("pg_advisory_unlock" in s for s in sql_texts)


# ─────────────────────────────────────────────────────────────
# tick: 拿不到 lock
# ─────────────────────────────────────────────────────────────


class TestTickNoLock:
    @pytest.mark.asyncio
    async def test_no_lock_skip(self, worker_mod, monkeypatch):
        sess = _FakeSession(got_lock=False, batch_rows=[])
        _patch_session(monkeypatch, worker_mod, sess)

        async def _fake_embed(texts, trace_id):
            raise AssertionError("must not embed when lock missed")

        monkeypatch.setattr(worker_mod, "embed", _fake_embed)

        stats = await worker_mod.run_one_tick(trace_id="t")
        assert stats["selected"] == 0
        assert stats["error"] is None
        # 没尝试 SELECT memories
        assert not any("FROM memories" in c[0] for c in sess.calls)


# ─────────────────────────────────────────────────────────────
# tick: 正常 backfill
# ─────────────────────────────────────────────────────────────


class TestTickHappy:
    @pytest.mark.asyncio
    async def test_batch_persisted(self, worker_mod, monkeypatch):
        id1, id2 = uuid4(), uuid4()
        rows = [(id1, "我喜欢爵士"), (id2, "下周去东京")]
        sess = _FakeSession(got_lock=True, batch_rows=rows)
        _patch_session(monkeypatch, worker_mod, sess)

        async def _fake_embed(texts, trace_id):
            assert texts == ["我喜欢爵士", "下周去东京"]
            return type(
                "R",
                (),
                {
                    "vectors": [[0.1] * 4, [0.2] * 4],
                    "error": None,
                    "model_used": "stub",
                    "usage": {},
                    "latency_ms": 1.0,
                },
            )()

        monkeypatch.setattr(worker_mod, "embed", _fake_embed)

        stats = await worker_mod.run_one_tick(trace_id="t")
        assert stats["selected"] == 2
        assert stats["embedded"] == 2
        assert stats["updated"] == 2
        assert stats["error"] is None

        # 验证 UPDATE 参数：vec 是 '[...]' 字符串、id 与 row 对齐
        updates = [c for c in sess.calls if c[0].startswith("UPDATE memories")]
        assert len(updates) == 2
        for sql, params in updates:
            assert "CAST(:vec AS vector)" in sql
            assert isinstance(params["vec"], str)
            assert params["vec"].startswith("[") and params["vec"].endswith("]")
            assert str(params["id"]) in (str(id1), str(id2))


# ─────────────────────────────────────────────────────────────
# tick: embed 失败
# ─────────────────────────────────────────────────────────────


class TestTickEmbedFail:
    @pytest.mark.asyncio
    async def test_embed_error_no_update(self, worker_mod, monkeypatch):
        id1 = uuid4()
        rows = [(id1, "hello")]
        sess = _FakeSession(got_lock=True, batch_rows=rows)
        _patch_session(monkeypatch, worker_mod, sess)

        async def _fake_embed(texts, trace_id):
            return type(
                "R",
                (),
                {
                    "vectors": [],
                    "error": "5xx:503:boom",
                    "model_used": "stub",
                    "usage": {},
                    "latency_ms": 1.0,
                },
            )()

        monkeypatch.setattr(worker_mod, "embed", _fake_embed)

        stats = await worker_mod.run_one_tick(trace_id="t")
        assert stats["selected"] == 1
        assert stats["embedded"] == 0
        assert stats["updated"] == 0
        assert stats["error"] == "5xx:503:boom"
        # 没有 UPDATE 语句被发
        assert not any(c[0].startswith("UPDATE memories") for c in sess.calls)


# ─────────────────────────────────────────────────────────────
# Scheduler start guards
# ─────────────────────────────────────────────────────────────


class TestSchedulerStart:
    def test_disabled_returns_none(self, worker_mod, monkeypatch):
        monkeypatch.setattr(worker_mod.settings, "EMBEDDING_WORKER_ENABLED", False, raising=False)
        monkeypatch.setattr(worker_mod.settings, "OPENAI_API_KEY", "sk-x", raising=False)
        assert worker_mod.start_scheduler() is None

    def test_no_key_returns_none(self, worker_mod, monkeypatch):
        monkeypatch.setattr(worker_mod.settings, "EMBEDDING_WORKER_ENABLED", True, raising=False)
        monkeypatch.setattr(worker_mod.settings, "OPENAI_API_KEY", None, raising=False)
        assert worker_mod.start_scheduler() is None


# ─────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────


class TestVectorLiteralReuse:
    def test_helper_present(self, worker_mod):
        s = worker_mod._vector_literal([0.1, 0.2, 0.3])
        assert s == "[0.1000000,0.2000000,0.3000000]"
