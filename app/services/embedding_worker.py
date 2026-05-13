"""D3-4: Embedding worker — fill memories.embedding for new rows.

设计要点
========
- APScheduler 在 FastAPI lifespan 里启动一个 IntervalTrigger（默认每 30s）。
- 每 tick：
  1. ``SELECT FOR UPDATE SKIP LOCKED`` 拉一批 ``embedding IS NULL`` 的 memories
     —— 多 worker / 多 pod 安全，不会重复处理同一行。
  2. 调 ``services.embedder.embed(batch)`` 求向量。
  3. 用 pgvector 的字符串字面量（``'[1,2,...]'::vector``）把结果写回。
- ``EMBEDDING_WORKER_ENABLED=False`` 时 scheduler 不启动（演示 / 离线开发）。
- ``OPENAI_API_KEY`` 未配置 → 同样不启动，log warning 提醒。
- 任何异常都吞掉并 log；scheduler 不会把 API 进程拖崩。

为什么不直接在 memory_writer 里同步 embed？
- D3-3 已经为每条用户消息花了一次 LLM 评分（约 0.5–1s）；再叠加 0.5s embedding
  会显著拉长用户回复路径。
- 用异步队列模式可以批处理（一次 64 条），单条平均成本 / 延迟都低；
  且 embedding 失败不影响 memories 行本身已经入库的事实。
- 留出未来切换 provider / 重算 embedding 的灵活度（行还在，重置 NULL 即可）。
"""
from __future__ import annotations

import time
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger
from sqlalchemy import text

from core.config import settings
from core.database import AsyncSessionLocal
from services.embedder import embed


# 固定 advisory lock key（与 silent_reactivation 错开）
_ADVISORY_LOCK_KEY = 6_300_410

JOB_ID = "embedding_backfill"

_scheduler: Optional[AsyncIOScheduler] = None


# ─────────────────────────────────────────────────────────────
# 单次 tick：拉一批 + embed + 写回
# ─────────────────────────────────────────────────────────────

async def run_one_tick(trace_id: Optional[str] = None) -> dict:
    """执行一次 backfill。返回统计 dict（便于测试 / 监控）。

    Returns:
        ``{"selected": N, "embedded": M, "updated": K, "error": str|None}``
    """
    trace_id = trace_id or f"embed-{int(time.time())}"
    log = logger.bind(component="embedding_worker", trace_id=trace_id)
    stats = {"selected": 0, "embedded": 0, "updated": 0, "error": None}

    batch_size = max(1, int(settings.EMBEDDING_BATCH_SIZE or 32))

    try:
        async with AsyncSessionLocal() as session:
            # advisory lock：保证一个时刻只有一个 tick 在跑
            got_lock = (
                await session.execute(
                    text("SELECT pg_try_advisory_lock(:k)"),
                    {"k": _ADVISORY_LOCK_KEY},
                )
            ).scalar()
            if not got_lock:
                log.info("embedding_worker.skip_no_lock")
                return stats

            try:
                rows = (
                    await session.execute(
                        text(
                            "SELECT id, content "
                            "FROM memories "
                            "WHERE is_active = true AND embedding IS NULL "
                            "ORDER BY created_at ASC "
                            "LIMIT :n "
                            "FOR UPDATE SKIP LOCKED"
                        ),
                        {"n": batch_size},
                    )
                ).fetchall()

                if not rows:
                    log.info("embedding_worker.tick.empty")
                    return stats

                stats["selected"] = len(rows)
                ids = [str(r[0]) for r in rows]
                texts = [r[1] or "" for r in rows]

                log.bind(batch=len(rows)).info("embedding_worker.tick.batch_pulled")

                result = await embed(texts, trace_id=trace_id)
                if result.error or not result.vectors:
                    stats["error"] = result.error or "no_vectors"
                    log.bind(error=stats["error"]).warning(
                        "embedding_worker.tick.embed_failed"
                    )
                    return stats

                stats["embedded"] = len(result.vectors)

                # 写回：逐行 UPDATE（一行一向量；BulkInsertMappings 对 vector
                # 类型不友好）。同事务下，advisory lock 还压着，安全。
                updated = 0
                for mem_id, vec in zip(ids, result.vectors):
                    if len(vec) == 0:
                        continue
                    vec_str = _vector_literal(vec)
                    await session.execute(
                        text(
                            "UPDATE memories "
                            "SET embedding = CAST(:vec AS vector), updated_at = NOW() "
                            "WHERE id = :id AND embedding IS NULL"
                        ),
                        {"vec": vec_str, "id": mem_id},
                    )
                    updated += 1

                await session.commit()
                stats["updated"] = updated

                log.bind(
                    selected=stats["selected"],
                    embedded=stats["embedded"],
                    updated=stats["updated"],
                    model=result.model_used,
                ).info("embedding_worker.tick.persisted")

            finally:
                await session.execute(
                    text("SELECT pg_advisory_unlock(:k)"),
                    {"k": _ADVISORY_LOCK_KEY},
                )
                await session.commit()

    except Exception as exc:
        log.bind(error_type=type(exc).__name__).exception(
            "embedding_worker.tick.error"
        )
        stats["error"] = f"{type(exc).__name__}:{exc}"

    return stats


# ─────────────────────────────────────────────────────────────
# Scheduler 控制
# ─────────────────────────────────────────────────────────────

def start_scheduler() -> Optional[AsyncIOScheduler]:
    """启动 backfill scheduler 单例。可重入：已启动则返回现有实例。

    短路条件：
      - settings.EMBEDDING_WORKER_ENABLED=False → no-op
      - settings.OPENAI_API_KEY 未配置 → no-op + warning
    """
    global _scheduler
    if not settings.EMBEDDING_WORKER_ENABLED:
        logger.bind(component="embedding_worker").info(
            "embedding_worker.scheduler.disabled"
        )
        return None
    if not settings.OPENAI_API_KEY:
        logger.bind(component="embedding_worker").warning(
            "embedding_worker.scheduler.no_api_key"
        )
        return None
    if _scheduler is not None:
        return _scheduler

    interval = max(5, int(settings.EMBEDDING_POLL_SECONDS or 30))
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        run_one_tick,
        trigger=IntervalTrigger(seconds=interval),
        id=JOB_ID,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.bind(
        component="embedding_worker",
        interval_s=interval,
        batch_size=settings.EMBEDDING_BATCH_SIZE,
    ).info("embedding_worker.scheduler.started")
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:
        logger.bind(component="embedding_worker").exception(
            "embedding_worker.scheduler.shutdown_error"
        )
    finally:
        _scheduler = None
        logger.bind(component="embedding_worker").info(
            "embedding_worker.scheduler.stopped"
        )


# ─────────────────────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────────────────────

def _vector_literal(vec: list[float]) -> str:
    """pgvector 字符串字面量：``[1.0, 2.0, ...]``。

    避免依赖 ``pgvector.psycopg`` / ``pgvector.sqlalchemy``——
    项目目前只用 asyncpg + plain SQL，字符串 CAST 最简单也最稳。
    """
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"
