from fastapi import APIRouter
from core.database import engine
from sqlalchemy import text
import redis.asyncio as aioredis
from core.config import settings

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "service": "ERIS API", "version": "0.1.0"}


@router.get("/health/detail")
async def health_detail():
    result = {"api": "ok", "db": "unknown", "redis": "unknown"}
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
    return result
