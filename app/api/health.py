
import time
from datetime import UTC, datetime

from fastapi import APIRouter
from core.database import engine
from sqlalchemy import text
import redis.asyncio as aioredis
from core.config import settings
from core.process_role import get_runtime_status
from loguru import logger

router = APIRouter()

@router.get("/health")
async def health():
    logger.info("health.check")
    runtime = get_runtime_status()
    return {
        "status": "ok",
        "service": "ERIS API",
        "version": "0.1.0",
        "timestamp": datetime.now(UTC).isoformat(),
        "process_role": runtime["process_role"],
        "runtime_ready": runtime["runtime_ready"],
    }

@router.get("/health/detail")
async def health_detail():
    started = time.perf_counter()
    runtime = get_runtime_status()
    result = {
        "api": "ok",
        "db": "unknown",
        "redis": "unknown",
        "process_role": runtime["process_role"],
        "runtime_ready": runtime["runtime_ready"],
        "owns_api_workers": runtime["owns_api_workers"],
        "owns_telegram_runtime": runtime["owns_telegram_runtime"],
    }
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        result["db"] = "ok"
    except Exception as e:
        result["db"] = str(e)
    try:
        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.close()
        result["redis"] = "ok"
    except Exception as e:
        result["redis"] = str(e)
    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
    logger.info("health.detail.check")
    return result
