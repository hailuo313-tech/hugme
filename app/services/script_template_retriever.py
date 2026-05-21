"""Vector-backed script template retrieval for P3-03/P3-04."""

from __future__ import annotations

import inspect
import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from sqlalchemy import text

from services.embedder import embed
from services.memory_retriever import _vector_literal

VALID_HOOKS = {
    "inbound",
    "consumption",
    "probe",
    "grading",
    "reply",
    "operator",
    "outbound",
    "archive",
}


@dataclass(frozen=True)
class ScriptTemplateQuery:
    query: str
    platform: str = "telegram_real_user"
    user_level: str | None = None
    persona_slug: str | None = None
    hook: str | None = None
    category_key: str | None = None
    language: str = "zh"
    limit: int = 3


@dataclass(frozen=True)
class ScriptTemplateHit:
    id: str
    category_key: str
    title: str
    content: str
    language: str
    platform: str
    user_level: str | None
    persona_slug: str | None
    hook: str | None
    similarity: float | None


@dataclass(frozen=True)
class ScriptTemplateSearchResult:
    hits: list[ScriptTemplateHit] = field(default_factory=list)
    embedding_used: bool = False
    fallback_reason: str | None = None
    latency_ms: float = 0.0


async def search_script_templates(
    *,
    db: Any,
    query: ScriptTemplateQuery,
    trace_id: str | None = None,
) -> ScriptTemplateSearchResult:
    started = time.perf_counter()
    limit = max(1, min(int(query.limit or 3), 3))
    clean_query = query.query.strip()
    if not clean_query:
        return ScriptTemplateSearchResult(
            fallback_reason="empty_query",
            latency_ms=_elapsed_ms(started),
        )

    qvec: list[float] | None = None
    embedding_used = False
    fallback_reason = None
    emb = await embed([clean_query], trace_id=trace_id or "script-template-search")
    if emb.error or not emb.vectors:
        fallback_reason = emb.error or "no_vector"
    else:
        qvec = emb.vectors[0]
        embedding_used = True

    rows = await _query_candidates(
        db=db,
        query=query,
        qvec=qvec,
        limit=limit,
    )
    hits = [_row_to_hit(row) for row in rows[:limit]]
    latency = _elapsed_ms(started)
    logger.bind(
        component="script_template_retriever",
        hits=len(hits),
        embedding_used=embedding_used,
        latency_ms=round(latency, 2),
    ).info("script_template.search.done")
    return ScriptTemplateSearchResult(
        hits=hits,
        embedding_used=embedding_used,
        fallback_reason=fallback_reason,
        latency_ms=latency,
    )


async def _query_candidates(
    *,
    db: Any,
    query: ScriptTemplateQuery,
    qvec: list[float] | None,
    limit: int,
) -> list[Any]:
    params: dict[str, Any] = {
        "language": query.language,
        "platform": query.platform,
        "limit": limit,
    }
    where = [
        "status = 'approved'",
        "language = :language",
        "(platform = :platform OR platform IS NULL)",
    ]

    if query.user_level:
        params["user_level"] = query.user_level.upper()
        where.append("(user_level = :user_level OR user_level IS NULL)")
    if query.persona_slug:
        params["persona_slug"] = query.persona_slug
        where.append("(persona_slug = :persona_slug OR persona_slug IS NULL)")
    if query.hook:
        hook = query.hook.strip()
        if hook not in VALID_HOOKS:
            raise ValueError(f"unknown script hook: {hook}")
        params["hook"] = hook
        where.append("(hook = :hook OR hook IS NULL)")
    if query.category_key:
        params["category_key"] = query.category_key
        where.append("category_key = :category_key")

    if qvec:
        params["qvec"] = _vector_literal(qvec)
        similarity_expr = "1 - (embedding <=> CAST(:qvec AS vector))"
        where.append("embedding IS NOT NULL")
        order = "similarity DESC, updated_at DESC"
    else:
        params["needle"] = f"%{query.query.strip()}%"
        similarity_expr = "NULL::float"
        order = (
            "CASE WHEN content ILIKE :needle OR title ILIKE :needle THEN 1 ELSE 0 END DESC, "
            "updated_at DESC, created_at DESC"
        )

    sql = f"""
        SELECT id, category_key, title, content, language, platform,
               user_level, persona_slug, hook, {similarity_expr} AS similarity
        FROM script_templates
        WHERE {' AND '.join(where)}
        ORDER BY {order}
        LIMIT :limit
    """
    result = await db.execute(text(sql), params)
    rows = result.fetchall()
    if inspect.isawaitable(rows):
        rows = await rows
    return list(rows)


def _row_to_hit(row: Any) -> ScriptTemplateHit:
    data = row._mapping if hasattr(row, "_mapping") else row
    return ScriptTemplateHit(
        id=str(data["id"]),
        category_key=str(data["category_key"]),
        title=str(data["title"]),
        content=str(data["content"]),
        language=str(data["language"]),
        platform=str(data["platform"]),
        user_level=data.get("user_level"),
        persona_slug=data.get("persona_slug"),
        hook=data.get("hook"),
        similarity=float(data["similarity"]) if data.get("similarity") is not None else None,
    )


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000
