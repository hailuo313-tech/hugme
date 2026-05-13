"""D4-1 单元测试：app/services/memory_retriever.py

覆盖：
- empty query → 直接 short-circuit
- happy path：embedder + DB stub，rerank 排序符合权重公式
- embed 失败：fallback 到 importance 排序，embedding_used=False
- DB 抛错：返回空 hits + fallback_reason
- memory_types / min_importance / character_id 参数正确进 SQL
- _compute_final_score：手算样例
- _vector_literal：格式
"""
from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

import pytest


# ─────────────────────────────────────────────────────────────
# fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def mr():
    import services.memory_retriever as mod  # type: ignore

    importlib.reload(mod)
    return mod


class _FakeMapping(dict):
    """模拟 SQLAlchemy Row._mapping —— 就是一个 dict。"""
    pass


class _FakeRow:
    def __init__(self, mapping: dict):
        self._mapping = _FakeMapping(mapping)


class _FakeResult:
    def __init__(self, rows: list[_FakeRow]):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeDB:
    """模拟 AsyncSession：记录 execute / commit。

    同时支持 `async with` 语义，可被当作 ``AsyncSessionLocal()`` 的返回值用。
    """

    def __init__(self, rows: Optional[list[dict]] = None, fail: bool = False):
        self.rows = rows or []
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, stmt, params=None):
        if self.fail:
            raise RuntimeError("db dead")
        sql = str(getattr(stmt, "text", stmt))
        self.calls.append((sql, params or {}))
        # SELECT vs UPDATE：UPDATE 命中 last_used_at 不返回行
        if "UPDATE memories" in sql:
            return _FakeResult([])
        return _FakeResult([_FakeRow(r) for r in self.rows])

    async def commit(self):
        self.commits += 1


def _patch_embed(monkeypatch, mr_mod, *, vectors=None, error=None):
    async def _fake(texts, trace_id):
        return type(
            "R",
            (),
            {
                "vectors": vectors or [],
                "error": error,
                "model_used": "stub",
                "usage": {},
                "latency_ms": 1.0,
            },
        )()

    monkeypatch.setattr(mr_mod, "embed", _fake)


def _row(
    *,
    rid: Optional[str] = None,
    content: str = "x",
    mtype: str = "preference",
    imp: float = 5.0,
    conf: float = 0.9,
    sim: float = 0.5,
    created_days_ago: int = 1,
) -> dict:
    return {
        "id": rid or str(uuid4()),
        "content": content,
        "memory_type": mtype,
        "importance_score": imp,
        "confidence_score": conf,
        "emotion_tags": [],
        "created_at": datetime.now(timezone.utc) - timedelta(days=created_days_ago),
        "last_used_at": None,
        "similarity": sim,
    }


# ─────────────────────────────────────────────────────────────
# Short-circuit / inputs
# ─────────────────────────────────────────────────────────────

class TestEarlyExit:
    @pytest.mark.asyncio
    async def test_empty_query(self, mr, monkeypatch):
        _patch_embed(monkeypatch, mr, vectors=[[0.1] * 4])
        db = _FakeDB()
        out = await mr.retrieve(db=db, user_id=str(uuid4()), query_text="   ")
        assert out.hits == []
        assert out.fallback_reason == "empty_query"
        assert db.calls == []  # 没碰 DB


# ─────────────────────────────────────────────────────────────
# Happy path
# ─────────────────────────────────────────────────────────────

class TestHappy:
    @pytest.mark.asyncio
    async def test_returns_topk_reranked(self, mr, monkeypatch):
        _patch_embed(monkeypatch, mr, vectors=[[0.1] * 8])
        rows = [
            _row(content="A", sim=0.95, imp=4, created_days_ago=120),
            _row(content="B", sim=0.85, imp=9, created_days_ago=2),
            _row(content="C", sim=0.30, imp=10, created_days_ago=1),
        ]
        db = _FakeDB(rows=rows)

        out = await mr.retrieve(
            db=db,
            user_id=str(uuid4()),
            query_text="女朋友最喜欢什么颜色",
            k_final=3,
        )
        assert out.embedding_used is True
        assert out.fallback_reason is None
        assert len(out.hits) == 3
        # 综合分应严格递减
        scores = [h.final_score for h in out.hits]
        assert scores == sorted(scores, reverse=True)
        # B (sim 高 + imp 高 + recent) 通常排第一
        assert out.hits[0].content == "B"

    @pytest.mark.asyncio
    async def test_sql_params_carry_filters(self, mr, monkeypatch):
        _patch_embed(monkeypatch, mr, vectors=[[0.1] * 4])
        db = _FakeDB(rows=[_row()])
        await mr.retrieve(
            db=db,
            user_id="u1",
            query_text="abc",
            memory_types=["preference", "goal"],
            min_importance=3.0,
            character_id="c1",
        )
        select_calls = [c for c in db.calls if c[0].lstrip().startswith("\n        SELECT") or "SELECT id" in c[0]]
        assert select_calls, "no SELECT issued"
        _sql, params = select_calls[0]
        assert params["uid"] == "u1"
        assert params["min_imp"] == 3.0
        assert params["types"] == ["preference", "goal"]
        assert params["cid"] == "c1"
        assert "qvec" in params and params["qvec"].startswith("[")

    @pytest.mark.asyncio
    async def test_touch_last_used_uses_own_session(self, mr, monkeypatch):
        """关键回归：fire-and-forget 必须用独立 AsyncSessionLocal()，
        不能借请求级 db。否则 sqlalchemy.exc.IllegalStateChangeError。
        2026-05-13 D4-1 上线时这个 bug 触发过一次。
        """
        _patch_embed(monkeypatch, mr, vectors=[[0.1] * 4])
        rows = [_row(rid="m1"), _row(rid="m2")]
        request_db = _FakeDB(rows=rows)

        # touch 应该用 _OwnDB 而不是 request_db
        own_db = _FakeDB(rows=[])
        monkeypatch.setattr(mr, "AsyncSessionLocal", lambda: own_db)

        await mr.retrieve(
            db=request_db,
            user_id="u",
            query_text="abc",
            k_final=2,
            touch_last_used=True,
        )
        import asyncio
        await asyncio.sleep(0.01)

        # request_db 只应被 SELECT，绝不 UPDATE（避免 session 状态冲突）
        request_updates = [c for c in request_db.calls if "UPDATE memories" in c[0]]
        assert request_updates == [], "must NOT update via request session"

        # own_db 应收到 UPDATE
        own_updates = [c for c in own_db.calls if "UPDATE memories" in c[0]]
        assert len(own_updates) == 1
        assert own_updates[0][1]["ids"] == ["m1", "m2"]
        assert own_db.commits == 1


# ─────────────────────────────────────────────────────────────
# Fallback paths
# ─────────────────────────────────────────────────────────────

class TestFallback:
    @pytest.mark.asyncio
    async def test_embed_failure_uses_importance_sort(self, mr, monkeypatch):
        _patch_embed(monkeypatch, mr, error="4xx:401")
        db = _FakeDB(rows=[_row(imp=8.0), _row(imp=3.0)])
        out = await mr.retrieve(db=db, user_id="u", query_text="abc")
        assert out.embedding_used is False
        assert out.fallback_reason == "4xx:401"
        assert len(out.hits) == 2
        # SQL 不应包含 vector 排序
        select = [c for c in db.calls if "SELECT id" in c[0]][0]
        assert "embedding <=>" not in select[0]
        assert "qvec" not in select[1]

    @pytest.mark.asyncio
    async def test_db_failure_returns_empty(self, mr, monkeypatch):
        _patch_embed(monkeypatch, mr, vectors=[[0.1] * 4])
        db = _FakeDB(fail=True)
        out = await mr.retrieve(db=db, user_id="u", query_text="abc")
        assert out.hits == []
        assert out.fallback_reason and out.fallback_reason.startswith("sql:")
        assert out.embedding_used is True  # query embed 是成功的

    @pytest.mark.asyncio
    async def test_empty_candidates(self, mr, monkeypatch):
        _patch_embed(monkeypatch, mr, vectors=[[0.1] * 4])
        db = _FakeDB(rows=[])
        out = await mr.retrieve(db=db, user_id="u", query_text="abc")
        assert out.hits == []
        assert out.candidates_scanned == 0


# ─────────────────────────────────────────────────────────────
# Pure helpers
# ─────────────────────────────────────────────────────────────

class TestRerankFormula:
    def test_recent_high_imp_high_sim_top(self, mr):
        now = datetime.now(timezone.utc)
        good = mr.MemoryHit(
            id="g",
            content="x",
            memory_type="preference",
            importance_score=9.0,
            confidence_score=0.95,
            emotion_tags=[],
            created_at=now - timedelta(days=1),
            last_used_at=None,
            similarity=0.9,
            final_score=0.0,
        )
        bad = mr.MemoryHit(
            id="b",
            content="x",
            memory_type="preference",
            importance_score=2.0,
            confidence_score=0.6,
            emotion_tags=[],
            created_at=now - timedelta(days=400),
            last_used_at=None,
            similarity=0.1,
            final_score=0.0,
        )
        s_good = mr._compute_final_score(good, now=now)
        s_bad = mr._compute_final_score(bad, now=now)
        assert s_good > s_bad
        # 分量都 ∈ [0,1]，加权总和也应 ≤ 1
        assert 0.0 <= s_good <= 1.0
        assert 0.0 <= s_bad <= 1.0

    def test_handles_naive_datetime(self, mr):
        now = datetime.now(timezone.utc)
        h = mr.MemoryHit(
            id="x",
            content="x",
            memory_type=None,
            importance_score=5.0,
            confidence_score=1.0,
            emotion_tags=[],
            created_at=datetime(2026, 5, 1),  # naive
            last_used_at=None,
            similarity=0.5,
            final_score=0.0,
        )
        s = mr._compute_final_score(h, now=now)
        assert 0.0 <= s <= 1.0


class TestVectorLiteral:
    def test_format(self, mr):
        s = mr._vector_literal([1.0, -2.0, 0.5])
        assert s == "[1.0000000,-2.0000000,0.5000000]"
