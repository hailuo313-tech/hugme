"""D4-1: Hybrid Memory Retrieval.

Pipeline
========
1. **Embed query** via ``services.embedder.embed``.
   - 失败 → 降级到 ``importance DESC`` 的 fallback；调用方仍能拿到结果，
     只是 ``embedding_used=False`` 提醒。
2. **Tag-filter SQL**：用 ``WHERE user_id / is_active / memory_type / character_id /
   importance_score`` 做硬过滤（B-tree 范围），同时 pgvector ``<=>`` 余弦距离
   ORDER BY 拿语义最相关的 ``k_candidates`` 行（默认 30）。
3. **Rerank** in Python：以语义 similarity 为主，融合 importance / recency /
   confidence，得到 ``final_score``，截 ``k_final``（默认 10）。
4. **Side effect**：对命中的 memory IDs 异步 ``UPDATE last_used_at = NOW()``；
   不阻塞返回。

为什么 Hybrid 而不是纯 vector
------------------------------
- 纯 vector：用户问"我女朋友最喜欢什么颜色？"——会召回所有谈到颜色 / 偏好的
  历史，但跨用户偏见、跨 character、importance=2 的废话也会进来。
- 纯 SQL：好过滤 user / type，但没法理解"颜色"≈"色彩"。
- Hybrid：用 SQL 把"哪些行是有效候选"先砍掉一刀（O(行) → O(k_candidates)），
  再让 cosine + rerank 做精排。生产典型规模（≤10k 行/用户），全表 + IVFFLAT 都能扛；
  IVFFLAT 索引留到 D8 性能调优阶段再加，不上预先优化。
- 余弦 vs L2：text-embedding-3-small 是 L2-normalized，两者排序等价，
  ``<=>`` 语义更直观（[0, 2] 越小越相似；similarity = 1 - distance ∈ [-1, 1]）。

Rerank 权重出处
---------------
- similarity 0.55 —— 语义相关是首要信号
- importance / 10 0.25 —— D3-3 LLM 评分；重要事实压过琐碎对话
- recency 0.15 —— 90 天指数衰减；旧事实不踢出但相对降权
- confidence 0.05 —— D3-3 LLM 的自评信心（一般 0.7–1.0），微调用

未来可以挂在 user_profile / character preset 上做 A/B；当前固定权重，可观察可调。
"""
from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from loguru import logger
from sqlalchemy import text

from core.database import AsyncSessionLocal
from services.embedder import embed


# ─────────────────────────────────────────────────────────────
# Public types
# ─────────────────────────────────────────────────────────────

@dataclass
class MemoryHit:
    """检索命中行，所有字段都对应 memories 表 + 计算得到的分数。"""

    id: str
    content: str
    memory_type: Optional[str]
    importance_score: float
    confidence_score: float
    emotion_tags: list
    created_at: Optional[datetime]
    last_used_at: Optional[datetime]
    similarity: float        # 1 - cosine_distance, ∈ [-1, 1]，越大越相关
    final_score: float       # rerank 综合分；越大越靠前


@dataclass
class RetrieveResult:
    hits: list[MemoryHit] = field(default_factory=list)
    embedding_used: bool = False
    fallback_reason: Optional[str] = None
    candidates_scanned: int = 0
    latency_ms: float = 0.0


# Rerank 权重；后续可由 character / experiment 注入。
RERANK_W_SIM = 0.55
RERANK_W_IMP = 0.25
RERANK_W_REC = 0.15
RERANK_W_CONF = 0.05
RECENCY_HALFLIFE_DAYS = 30.0  # exp 衰减半衰期，30 天后 recency=0.5


# ─────────────────────────────────────────────────────────────
# Main entry
# ─────────────────────────────────────────────────────────────

async def retrieve(
    *,
    db: Any,
    user_id: str,
    query_text: str,
    k_final: int = 10,
    k_candidates: int = 30,
    memory_types: Optional[Iterable[str]] = None,
    min_importance: float = 0.0,
    character_id: Optional[str] = None,
    include_global: bool = True,
    trace_id: Optional[str] = None,
    touch_last_used: bool = True,
) -> RetrieveResult:
    """检索一个用户最相关的 memories。

    所有失败都被吞掉并降级，绝不抛异常 —— 调用方拿到的 RetrieveResult
    总是有意义的（可能是空 list / 也可能是 fallback list）。
    """
    trace_id = trace_id or f"retrieve-{int(time.time())}"
    log = logger.bind(component="memory_retriever", trace_id=trace_id, user_id=user_id)
    started = time.time()

    if not query_text or not query_text.strip():
        log.info("retriever.skip.empty_query")
        return RetrieveResult(
            embedding_used=False,
            fallback_reason="empty_query",
            latency_ms=(time.time() - started) * 1000,
        )

    k_final = max(1, min(k_final, 50))
    k_candidates = max(k_final, min(k_candidates, 200))

    # ── Phase 1：query embedding ────────────────────────────
    emb = await embed([query_text], trace_id=trace_id)
    qvec: Optional[list[float]] = None
    embedding_used = False
    fallback_reason: Optional[str] = None
    if emb.error or not emb.vectors:
        fallback_reason = emb.error or "no_vector"
        log.bind(error=fallback_reason).warning("retriever.embed.fallback")
    else:
        qvec = emb.vectors[0]
        embedding_used = True

    # ── Phase 2：tag filter + (cosine ORDER BY) ─────────────
    try:
        rows = await _candidate_query(
            db=db,
            user_id=user_id,
            qvec=qvec,
            k_candidates=k_candidates,
            memory_types=list(memory_types) if memory_types else None,
            min_importance=min_importance,
            character_id=character_id,
            include_global=include_global,
        )
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).exception("retriever.sql.failed")
        return RetrieveResult(
            embedding_used=embedding_used,
            fallback_reason=f"sql:{type(exc).__name__}",
            latency_ms=(time.time() - started) * 1000,
        )

    if not rows:
        log.info("retriever.empty_candidates")
        return RetrieveResult(
            embedding_used=embedding_used,
            fallback_reason=fallback_reason,
            candidates_scanned=0,
            latency_ms=(time.time() - started) * 1000,
        )

    # ── Phase 3：rerank ────────────────────────────────────
    hits = [_row_to_hit(r) for r in rows]
    now = datetime.now(timezone.utc)
    for h in hits:
        h.final_score = _compute_final_score(h, now=now)
    hits.sort(key=lambda h: h.final_score, reverse=True)
    top = hits[:k_final]

    # ── Phase 4：side effect — touch last_used_at ──────────
    # 关键：开自己的 AsyncSessionLocal，不能借请求级 db。
    # 否则 fire-and-forget task 会在 FastAPI 关 session 后还在 execute()，
    # 触发 sqlalchemy.exc.IllegalStateChangeError。这是 D3-3 memory_writer
    # 早就修过的同一个坑，D4-1 上线时复发，2026-05-13 hotfix。
    if touch_last_used and top:
        ids = [h.id for h in top]
        try:
            asyncio.create_task(_touch_last_used(ids=ids, trace_id=trace_id))
        except RuntimeError:
            # 极少数：调用方没在 event loop 里跑（同步上下文）
            log.warning("retriever.touch.no_loop")

    latency = (time.time() - started) * 1000
    log.bind(
        candidates=len(hits),
        returned=len(top),
        top_sim=round(top[0].similarity, 4) if top else None,
        top_score=round(top[0].final_score, 4) if top else None,
        embedding_used=embedding_used,
        duration_ms=round(latency, 1),
    ).info("retriever.done")

    return RetrieveResult(
        hits=top,
        embedding_used=embedding_used,
        fallback_reason=fallback_reason,
        candidates_scanned=len(hits),
        latency_ms=latency,
    )


# ─────────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────────

async def _candidate_query(
    *,
    db: Any,
    user_id: str,
    qvec: Optional[list[float]],
    k_candidates: int,
    memory_types: Optional[list[str]],
    min_importance: float,
    character_id: Optional[str],
    include_global: bool,
) -> list[Any]:
    """两条路径：
       - 有 query embedding：ORDER BY embedding <=> :qvec
       - 没 embedding：ORDER BY importance_score DESC（fallback）
    返回 SQLAlchemy Row 列表。
    """
    params: dict = {
        "uid": user_id,
        "k": k_candidates,
        "min_imp": float(min_importance),
    }

    where = [
        "user_id = :uid",
        "is_active = true",
        "importance_score >= :min_imp",
    ]
    if memory_types:
        # 用 ANY(:types) 而不是 IN (...)，给 asyncpg 一个数组而不是元组
        params["types"] = list(memory_types)
        where.append("memory_type = ANY(:types)")
    if character_id:
        params["cid"] = character_id
        if include_global:
            where.append("(character_id = :cid OR memory_scope = 'global' OR character_id IS NULL)")
        else:
            where.append("character_id = :cid")

    if qvec:
        # 有向量：要求行本身也有 embedding（否则 <=> 报错）
        where.append("embedding IS NOT NULL")
        params["qvec"] = _vector_literal(qvec)
        order = "embedding <=> CAST(:qvec AS vector) ASC"
        sim_expr = "1 - (embedding <=> CAST(:qvec AS vector))"
    else:
        # 没向量：fallback 不需要 embedding 字段，importance 排序
        order = "importance_score DESC, created_at DESC"
        sim_expr = "NULL::float"

    sql = f"""
        SELECT id, content, memory_type, importance_score, confidence_score,
               emotion_tags, created_at, last_used_at,
               {sim_expr} AS similarity
        FROM memories
        WHERE {' AND '.join(where)}
        ORDER BY {order}
        LIMIT :k
    """

    result = await db.execute(text(sql), params)
    return list(result.fetchall())


def _row_to_hit(row: Any) -> MemoryHit:
    m = row._mapping if hasattr(row, "_mapping") else row
    sim = m.get("similarity")
    return MemoryHit(
        id=str(m["id"]),
        content=m.get("content") or "",
        memory_type=m.get("memory_type"),
        importance_score=float(m.get("importance_score") or 0.0),
        confidence_score=float(m.get("confidence_score") or 1.0),
        emotion_tags=list(m.get("emotion_tags") or []),
        created_at=m.get("created_at"),
        last_used_at=m.get("last_used_at"),
        similarity=float(sim) if sim is not None else 0.0,
        final_score=0.0,  # 待 rerank 填
    )


def _compute_final_score(h: MemoryHit, *, now: datetime) -> float:
    """加权融合：similarity / importance / recency / confidence。

    所有分量归一到 [0, 1] 后再加权，最终也在 ~[0, 1] 区间（理论上限 1.0）。
    """
    sim_norm = max(0.0, min(1.0, (h.similarity + 1.0) / 2.0))  # [-1,1] → [0,1]
    imp_norm = max(0.0, min(1.0, h.importance_score / 10.0))   # D3-3 评分上限 10
    conf_norm = max(0.0, min(1.0, h.confidence_score))

    if h.created_at is None:
        rec_norm = 0.5
    else:
        # 兼容 naive datetime（DB 可能返回不带 tz 的 TIMESTAMP）
        created = h.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (now - created).total_seconds() / 86400.0)
        rec_norm = math.exp(-age_days * math.log(2) / RECENCY_HALFLIFE_DAYS)

    return (
        RERANK_W_SIM * sim_norm
        + RERANK_W_IMP * imp_norm
        + RERANK_W_REC * rec_norm
        + RERANK_W_CONF * conf_norm
    )


async def _touch_last_used(*, ids: list[str], trace_id: str) -> None:
    """异步把命中行的 last_used_at 推到 NOW()。

    自带 ``AsyncSessionLocal()`` —— **绝不**借请求级 db session，
    因为 fire-and-forget task 的生命周期超过 FastAPI 请求作用域，
    共享 session 会触发 ``IllegalStateChangeError``（D3-3 同样的坑）。
    失败不影响检索结果。
    """
    log = logger.bind(component="memory_retriever", trace_id=trace_id)
    try:
        async with AsyncSessionLocal() as own_db:
            await own_db.execute(
                text(
                    "UPDATE memories SET last_used_at = NOW() "
                    "WHERE id = ANY(:ids)"
                ),
                {"ids": ids},
            )
            await own_db.commit()
        log.bind(touched=len(ids)).info("retriever.touch.ok")
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("retriever.touch.failed")


def _vector_literal(vec: list[float]) -> str:
    """pgvector 字符串字面量；与 embedding_worker 一致以保证读写对称。"""
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"
