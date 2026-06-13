"""
D1-2: POST /api/v1/messages/inbound
- 入库（users / conversations / messages 表）
- Redis 短期上下文写入（最近 20 条，key: ctx:{conversation_id}）
- 幂等键支持（header Idempotency-Key 或 metadata.tg_message_id）
- 返回 202 Accepted
- trace_id 贯穿全链路日志
"""
from fastapi import APIRouter, Depends, Request, Header, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from core.database import get_db
from core.config import settings
from pydantic import BaseModel, Field
from typing import Optional
from loguru import logger
import asyncio
import uuid, json, time
import redis.asyncio as aioredis

from services.memory_writer import maybe_write_memory
from services.age_extraction import maybe_extract_and_write_age
from services.user_level_service import user_level_service
from services.geoip_service import get_geoip_service
from services.profile_intake import (
    country_from_headers,
    country_from_metadata,
    country_from_text_language,
    extract_age_from_text,
    normalize_country_code,
    read_profile_completeness,
    write_age,
    write_country_code,
)

router = APIRouter()

# Redis 连接（懒加载单例）
_redis_client = None

async def get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


# ── 常量 ──────────────────────────────────────────────
CONTEXT_MAX_MESSAGES = 20          # 短期上下文保留条数
CONTEXT_TTL_SECONDS  = 86400 * 3   # 3 天无活动后过期
RATE_LIMIT_PER_MIN   = 20          # 每用户每分钟上限
RATE_LIMIT_PER_HOUR  = 200         # 每用户每小时上限


class InboundMessageRequest(BaseModel):
    channel: str                              # telegram / app / web
    external_user_id: str
    message_type: str = "text"               # text / image / audio
    content: str = Field(max_length=8000)
    metadata: Optional[dict] = {}


class InboundMessageResponse(BaseModel):
    message_id: str
    conversation_id: str
    status: str                               # accepted / blocked_by_rate_limit / blocked_by_safety
    trace_id: str
    block_reason: Optional[str] = None


# ── 工具函数 ──────────────────────────────────────────

def _make_trace_id() -> str:
    return str(uuid.uuid4()).replace("-", "")[:16]


async def _check_rate_limit(redis, user_id: str, trace_id: str) -> tuple[bool, str]:
    """返回 (passed, reason)"""
    now = int(time.time())
    pipe = redis.pipeline()

    min_key  = f"rl:min:{user_id}:{now // 60}"
    hour_key = f"rl:hour:{user_id}:{now // 3600}"

    pipe.incr(min_key)
    pipe.expire(min_key, 70)
    pipe.incr(hour_key)
    pipe.expire(hour_key, 3700)

    results = await pipe.execute()
    min_count, _, hour_count, _ = results

    if min_count > RATE_LIMIT_PER_MIN:
        logger.warning(f"[{trace_id}] rate_limit.per_minute user_id={user_id} count={min_count}")
        return False, "rate_limited_per_minute"
    if hour_count > RATE_LIMIT_PER_HOUR:
        logger.warning(f"[{trace_id}] rate_limit.per_hour user_id={user_id} count={hour_count}")
        return False, "rate_limited_per_hour"
    return True, ""


async def _push_context(redis, conv_id: str, role: str, content: str, msg_id: str):
    """
    向 Redis List 追加消息，保留最近 CONTEXT_MAX_MESSAGES 条。
    key: ctx:{conv_id}
    value: JSON {role, content, msg_id, ts}
    """
    key = f"ctx:{conv_id}"
    entry = json.dumps({
        "role":    role,
        "content": content,
        "msg_id":  msg_id,
        "ts":      int(time.time()),
    }, ensure_ascii=False)

    pipe = redis.pipeline()
    pipe.rpush(key, entry)
    pipe.ltrim(key, -CONTEXT_MAX_MESSAGES, -1)   # 只保留最后 20 条
    pipe.expire(key, CONTEXT_TTL_SECONDS)
    await pipe.execute()


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or None
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else None


async def _persist_technical_profile_signals(
    db: AsyncSession,
    *,
    user_id: str,
    request: Request,
    metadata: dict,
    content: str,
    log,
) -> None:
    completeness = await read_profile_completeness(db, user_id=user_id)

    if completeness.country_code is None:
        country_code = country_from_metadata(metadata) or country_from_headers(request.headers)
        source = "metadata_or_header"
        if not country_code:
            ip = _client_ip(request)
            if ip:
                try:
                    result = await get_geoip_service().lookup(ip)
                    country_code = normalize_country_code(
                        result.country_code if result else None
                    )
                    source = "geoip"
                except Exception as exc:
                    log.bind(error_type=type(exc).__name__).warning("message.geoip.failed")
        if not country_code:
            country_code = country_from_text_language(content)
            source = "language_fallback"
        if country_code:
            await write_country_code(
                db,
                user_id=user_id,
                country_code=country_code,
                source=source,
            )
            log.bind(country_code=country_code, source=source).info(
                "message.profile.country_detected"
            )

    if completeness.age is None:
        age = (
            extract_age_from_text(str(metadata.get("age") or ""))
            if metadata.get("age") is not None
            else None
        )
        age = age or extract_age_from_text(content)
        if age is not None:
            await write_age(db, user_id=user_id, age=age, source="metadata_or_text")
            log.bind(age=age).info("message.profile.age_detected")


# ── 路由 ──────────────────────────────────────────────

@router.post(
    "/inbound",
    status_code=202,
    response_model=InboundMessageResponse,
    summary="用户消息入口（统一入站）",
)
async def inbound_message(
    data: InboundMessageRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    trace_id = getattr(request.state, "trace_id", _make_trace_id())
    start_ts = time.time()

    # ── 解析幂等键 ──────────────────────────────────────
    # 优先 header > metadata.tg_message_id > 无（不做幂等）
    meta = data.metadata or {}
    idem_key = (
        idempotency_key
        or (f"tg-{meta['tg_message_id']}" if meta.get("tg_message_id") else None)
    )

    log = logger.bind(
        trace_id=trace_id,
        channel=data.channel,
        external_user_id=data.external_user_id,
        message_type=data.message_type,
        idempotency_key=idem_key,
    )
    log.info("message.inbound.received")

    redis = await get_redis()

    # ── 幂等检查 ─────────────────────────────────────────
    if idem_key:
        cached = await redis.get(f"idem:{idem_key}")
        if cached:
            log.info("message.inbound.idempotent_hit")
            return JSONResponse(status_code=202, content=json.loads(cached))

    # ── 查或建 user ──────────────────────────────────────
    row = (await db.execute(
        text(
            "SELECT id, status, is_minor_suspected "
            "FROM users WHERE channel=:ch AND external_id=:eid"
        ),
        {"ch": data.channel, "eid": data.external_user_id}
    )).fetchone()

    if row:
        user_id = str(row[0])
        user_status = str(row[1] or "active")
        is_minor_suspected = bool(row[2]) if len(row) > 2 else False
        if user_status != "active":
            resp_body = {
                "message_id": "",
                "conversation_id": "",
                "status": "blocked_by_user_status",
                "trace_id": trace_id,
                "block_reason": f"user_status:{user_status}",
            }
            log.bind(user_id=user_id, user_status=user_status).info(
                "message.inbound.user_status_blocked"
            )
            return JSONResponse(status_code=423, content=resp_body)
        log.bind(user_id=user_id).info("message.inbound.user.found")
    else:
        user_id = str(uuid.uuid4())
        await db.execute(
            text("INSERT INTO users (id,channel,external_id) VALUES (:id,:ch,:eid)"),
            {"id": user_id, "ch": data.channel, "eid": data.external_user_id}
        )
        await db.execute(
            text("INSERT INTO user_profiles (user_id) VALUES (:uid)"),
            {"uid": user_id}
        )
        await db.commit()
        is_minor_suspected = False
        log.bind(user_id=user_id).info("message.inbound.user.created")

    await _persist_technical_profile_signals(
        db,
        user_id=user_id,
        request=request,
        metadata=meta,
        content=data.content,
        log=log,
    )
    await db.commit()
    level_result = await user_level_service.calculate_and_persist_user_level(
        db,
        user_id=user_id,
        external_user_id=data.external_user_id,
        country_code=country_from_metadata(meta) or country_from_headers(request.headers),
    )
    log.bind(
        user_level=level_result["level"],
        chat_route=level_result["chat_route"],
        level_reason=level_result["reason"],
    ).info("message.profile.level_classified")
    await db.commit()

    # ── 限流（用 user_id，比 external_id 更精确）────────────
    passed, reason = await _check_rate_limit(redis, user_id, trace_id)
    if not passed:
        resp_body = {
            "message_id":      "",
            "conversation_id": "",
            "status":          "blocked_by_rate_limit",
            "trace_id":        trace_id,
            "block_reason":    reason,
        }
        response.headers["Retry-After"] = "60"
        return JSONResponse(status_code=429, content=resp_body)

    # ── 查或建 conversation ──────────────────────────────
    conv_row = (await db.execute(
        text(
            "SELECT id FROM conversations "
            "WHERE user_id=:uid AND state NOT IN ('CLOSED','ESCALATED') "
            "ORDER BY updated_at DESC LIMIT 1"
        ),
        {"uid": user_id}
    )).fetchone()

    if conv_row:
        conv_id = str(conv_row[0])
        log.bind(conversation_id=conv_id).info("message.inbound.conversation.found")
    else:
        conv_id = str(uuid.uuid4())
        await db.execute(
            text("INSERT INTO conversations (id,user_id,channel,state) VALUES (:id,:uid,:ch,'AI_ACTIVE')"),
            {"id": conv_id, "uid": user_id, "ch": data.channel}
        )
        log.bind(conversation_id=conv_id).info("message.inbound.conversation.created")

    # ── 写入 messages 表 ─────────────────────────────────
    msg_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO messages "
            "(id,conversation_id,sender_type,sender_id,content,content_type) "
            "VALUES (:id,:cid,'user',:sid,:ct,:ctype)"
        ),
        {
            "id": msg_id,
            "cid": conv_id,
            "sid": user_id,
            "ct": data.content,
            "ctype": data.message_type,
        },
    )
    await db.execute(
        text("UPDATE conversations SET last_message_at=NOW(), updated_at=NOW() WHERE id=:id"),
        {"id": conv_id}
    )
    await db.commit()
    log.bind(message_id=msg_id).info("message.inbound.persisted")

    # ── Redis 短期上下文（最近 20 条）────────────────────
    try:
        await _push_context(redis, conv_id, "user", data.content, msg_id)
        log.bind(conversation_id=conv_id).info("message.inbound.context.pushed")
    except Exception as e:
        # Redis 失败不阻塞主流程，仅记录警告
        log.warning(f"message.inbound.context.push_failed err={e}")

    # ── D3-3: 触发记忆写入（fire-and-forget）─────────────
    # /inbound 不识别 onboarding 状态（那是 telegram.py 的职责），
    # 默认 is_onboarding=False；memory_writer 内部还有 prefilter 兜底。
    try:
        asyncio.create_task(
            maybe_write_memory(
                user_id=user_id,
                conversation_id=conv_id,
                message_id=msg_id,
                content=data.content,
                trace_id=trace_id,
                redis=redis,
            )
        )
    except Exception as e:
        log.warning(f"message.inbound.memory_writer.spawn_failed err={e}")

    # P2-04: AI extracts age and writes only high-confidence results.
    try:
        asyncio.create_task(
            maybe_extract_and_write_age(
                user_id=user_id,
                content=data.content,
                trace_id=trace_id,
            )
        )
    except Exception as e:
        log.warning(f"message.inbound.age_extraction.spawn_failed err={e}")

    # ── 构造响应并缓存幂等结果 ────────────────────────────
    elapsed = (time.time() - start_ts) * 1000
    log.bind(elapsed_ms=round(elapsed, 1)).info("message.inbound.complete")

    resp_body = {
        "message_id":      msg_id,
        "conversation_id": conv_id,
        "status":          "accepted",
        "trace_id":        trace_id,
        "block_reason":    None,
    }

    if idem_key:
        # 幂等缓存 24 小时
        await redis.set(f"idem:{idem_key}", json.dumps(resp_body), ex=86400)

    return JSONResponse(status_code=202, content=resp_body)
