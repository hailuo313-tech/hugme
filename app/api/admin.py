"""
D5-1 / D5-2: Admin 后台 API
- POST /api/v1/admin/login                          — operator 登录，返回 JWT
- GET  /api/v1/admin/me                             — 验证 token，返回当前 operator 信息
- GET  /api/v1/admin/conversations                  — D5-2 会话列表（分页 + 过滤）
- GET  /api/v1/admin/conversations/{conversation_id}— D5-2 会话详情（含最近 50 条消息）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from core.database import get_db
from services.dashboard_integration import sql_order_clause_for_dashboard
from core.config import settings
from pydantic import BaseModel
from typing import Any, Optional
from fastapi import Request
from loguru import logger
from decimal import Decimal
from enum import Enum
import hashlib, hmac, uuid, time, json, base64

from services.silent_reactivation_runner import run_silent_reactivation_scan

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)

# ── JWT (HS256, pure stdlib — no external dep) ────────────────────────

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def _sign_jwt(payload: dict, secret: str, expires_in: int = 86400 * 7) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = dict(payload)
    payload["exp"] = int(time.time()) + expires_in
    payload["iat"] = int(time.time())
    body   = _b64url(json.dumps(payload).encode())
    sig_input = f"{header}.{body}".encode()
    sig = hmac.new(secret.encode(), sig_input, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url(sig)}"

def _verify_jwt(token: str, secret: str) -> Optional[dict]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b, body_b, sig_b = parts
        sig_input = f"{header_b}.{body_b}".encode()
        expected = hmac.new(secret.encode(), sig_input, hashlib.sha256).digest()
        # pad base64
        pad = lambda s: s + "=" * (-len(s) % 4)
        actual = base64.urlsafe_b64decode(pad(sig_b))
        if not hmac.compare_digest(expected, actual):
            return None
        payload = json.loads(base64.urlsafe_b64decode(pad(body_b)))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None

def _hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

# ── Schemas ──────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    token: str
    operator_id: str
    username: str
    display_name: Optional[str]
    role: str

class MeResponse(BaseModel):
    operator_id: str
    username: str
    display_name: Optional[str]
    role: str


class ConversationOperatorReplyRequest(BaseModel):
    content: str
    used_script_id: Optional[str] = None

# ── Auth dependency ──────────────────────────────────────────────────

async def require_operator(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    if creds is None or not getattr(creds, "credentials", ""):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    payload = _verify_jwt(creds.credentials, settings.SECRET_KEY)
    if not payload or payload.get("type") != "operator":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return payload

# ── Routes ───────────────────────────────────────────────────────────

@router.post(
    "/admin/login",
    response_model=LoginResponse,
    summary="Operator 登录（返回 JWT）",
)
async def admin_login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    pw_hash = _hash_password(data.password)
    row = (await db.execute(
        text("""
            SELECT id, username, display_name, role
            FROM operators
            WHERE username = :u AND password_hash = :ph AND status = 'active'
        """),
        {"u": data.username, "ph": pw_hash},
    )).fetchone()

    if not row:
        logger.warning(f"admin_login.failed username={data.username}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    op_id, username, display_name, role = str(row[0]), row[1], row[2], row[3]
    token = _sign_jwt(
        {"sub": op_id, "username": username, "role": role, "type": "operator"},
        settings.SECRET_KEY,
    )
    logger.info(f"admin_login.success operator_id={op_id}")
    return LoginResponse(
        token=token,
        operator_id=op_id,
        username=username,
        display_name=display_name,
        role=role,
    )


@router.get(
    "/admin/me",
    response_model=MeResponse,
    summary="获取当前 Operator 信息",
)
async def admin_me(
    payload: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("SELECT id, username, display_name, role FROM operators WHERE id=:id"),
        {"id": payload["sub"]},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Operator not found")
    return MeResponse(
        operator_id=str(row[0]),
        username=row[1],
        display_name=row[2],
        role=row[3],
    )


# ── D5-2: 会话列表 + 详情 ─────────────────────────────────────────────

# 允许过滤的会话状态白名单（与 conversations.state 枚举对齐）
_ALLOWED_CONV_STATES = {"AI_ACTIVE", "WAITING_OPERATOR", "HUMAN_LOCKED", "CLOSED"}
_ALLOWED_CHANNELS = {"telegram", "whatsapp", "web", "discord"}


def _serialize_row(row: Any) -> dict:
    """JSON-safe row mapping (PG numeric -> float, uuid/datetime -> str)."""
    out: dict[str, Any] = {}
    for k, v in dict(row._mapping).items():
        if v is None:
            out[k] = None
        elif isinstance(v, uuid.UUID):
            out[k] = str(v)
        elif isinstance(v, Decimal):
            out[k] = float(v)
        elif isinstance(v, Enum):
            out[k] = v.value
        elif hasattr(v, "isoformat") and callable(getattr(v, "isoformat")):
            out[k] = v.isoformat()
        elif isinstance(v, (dict, list, int, float, str, bool)):
            out[k] = v
        else:
            out[k] = str(v)
    return out


async def _clear_deleted_message_context(user_id: str | None, conversation_ids: list[str]) -> None:
    """Best-effort cache cleanup after admin deletes persisted chat history."""
    try:
        from api.messages import get_redis
        from services.conversation_context import conversation_context_key

        redis = await get_redis()
        keys = [f"ctx:{cid}" for cid in conversation_ids if cid]
        if user_id:
            keys.append(conversation_context_key(user_id))
        if keys:
            await redis.delete(*keys)
    except Exception as exc:  # pragma: no cover - cache cleanup must not block admin delete
        logger.bind(error_type=type(exc).__name__).warning("admin.chat_history.cache_clear_failed")


def _require_uuid(value: str, field_name: str) -> None:
    try:
        uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field_name} must be a valid UUID")


def _telegram_chat_id_from_external(external_id: str | None) -> int | None:
    if not external_id or not str(external_id).startswith("tg_"):
        return None
    try:
        return int(str(external_id)[3:])
    except ValueError:
        return None


async def _send_operator_reply_to_telegram_real_user(
    *,
    chat_id: int,
    content: str,
    trace_id: str | None,
) -> tuple[bool, str | None]:
    try:
        from telethon.tl.types import PeerUser
        from services.mtproto.human_like_send import HumanLikeSendPolicy, send_human_like_message
        from services.telegram_account_manager import telegram_account_manager

        client = await telegram_account_manager.get_any_connected_client()
        if client is None:
            return False, "telegram_real_user_account_missing"

        peer = PeerUser(user_id=chat_id)
        get_input_entity = getattr(client, "get_input_entity", None)
        if callable(get_input_entity):
            try:
                peer = await get_input_entity(peer)
            except Exception:
                pass

        # Operator-confirmed sends should happen immediately after click; keep
        # typing indication but avoid the long automated delay profile.
        policy = HumanLikeSendPolicy(
            short_text_seconds=0.2,
            medium_text_seconds=0.2,
            long_text_seconds=0.2,
            extended_text_seconds=0.2,
            very_long_text_seconds=0.2,
            minimum_typing_seconds=0.2,
            minimum_inter_message_seconds=0.0,
        )
        sent = await send_human_like_message(client, peer, content, policy=policy)
        sent_id = getattr(sent, "id", None)
        return True, str(sent_id) if sent_id is not None else None
    except Exception as exc:
        logger.bind(
            trace_id=trace_id,
            chat_id=chat_id,
            error_type=type(exc).__name__,
        ).warning("admin.conversations.operator_reply.mtproto_failed")
        return False, "telegram_real_user_send_failed"


@router.get(
    "/admin/conversations",
    summary="D5-2：会话列表（分页 + state/channel/search 过滤；需要 operator JWT）",
)
async def admin_list_conversations(
    page: int = Query(1, ge=1, description="页码，1-based"),
    page_size: int = Query(20, ge=1, le=100, description="每页大小，最大 100"),
    state: Optional[str] = Query(None, description=f"按会话状态过滤；可选值：{sorted(_ALLOWED_CONV_STATES)}"),
    channel: Optional[str] = Query(None, description=f"按渠道过滤；可选值：{sorted(_ALLOWED_CHANNELS)}"),
    search: Optional[str] = Query(None, description="按用户 nickname / external_id 模糊搜索（ILIKE）"),
    payload: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    if state and state not in _ALLOWED_CONV_STATES:
        raise HTTPException(status_code=400, detail=f"state must be one of {sorted(_ALLOWED_CONV_STATES)}")
    if channel and channel not in _ALLOWED_CHANNELS:
        raise HTTPException(status_code=400, detail=f"channel must be one of {sorted(_ALLOWED_CHANNELS)}")

    search_like = f"%{search.strip()}%" if search and search.strip() else None

    params: dict[str, Any] = {
        "state": state,
        "channel": channel,
        "search": search_like,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }

    where = """
        WHERE (CAST(:state   AS TEXT) IS NULL OR c.state   = :state)
          AND (CAST(:channel AS TEXT) IS NULL OR c.channel = :channel)
          AND (CAST(:search  AS TEXT) IS NULL OR u.nickname ILIKE :search OR u.external_id ILIKE :search)
    """

    total_row = (await db.execute(
        text(f"""
            SELECT COUNT(*)
            FROM conversations c
            LEFT JOIN users u ON u.id = c.user_id
            {where}
        """),
        params,
    )).fetchone()
    raw_total = total_row[0] if total_row else 0
    if isinstance(raw_total, Decimal):
        total = int(raw_total)
    else:
        total = int(raw_total or 0)

    rows = (await db.execute(
        text(f"""
            SELECT
              c.id                                            AS conversation_id,
              c.state, c.handoff_count, c.channel,
              c.last_message_at, c.created_at,
              c.assigned_operator_id,
              u.id          AS user_id,
              u.nickname,
              u.external_id,
              u.channel     AS user_channel,
              u.risk_level,
              u.status      AS user_status,
              p.loneliness_score,
              p.vip_level,
              p.relationship_stage,
              ch.id         AS character_id,
              ch.name       AS character_name
            FROM conversations c
            LEFT JOIN users          u  ON u.id  = c.user_id
            LEFT JOIN user_profiles  p  ON p.user_id = u.id
            LEFT JOIN characters     ch ON ch.id = c.character_id
            {where}
            {sql_order_clause_for_dashboard()}
            LIMIT :limit OFFSET :offset
        """),
        params,
    )).fetchall()

    items = [_serialize_row(r) for r in rows]

    logger.bind(
        operator_id=payload.get("sub"),
        page=page, page_size=page_size,
        state=state, channel=channel, search_hit=bool(search_like),
        total=total, returned=len(items),
    ).info("admin.conversations.list")

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get(
    "/admin/conversations/{conversation_id}",
    summary="D5-2：会话详情（会话元信息 + 用户画像 + 最近 50 条消息；需要 operator JWT）",
)
async def admin_get_conversation_detail(
    conversation_id: str,
    payload: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    # 校验 UUID 格式（防 SQL 出错时落到 5xx）
    _require_uuid(conversation_id, "conversation_id")

    head_row = (await db.execute(
        text("""
            SELECT
              c.id                                            AS conversation_id,
              c.state, c.handoff_count, c.channel,
              c.last_message_at, c.created_at,
              c.assigned_operator_id, c.ai_model_used,
              u.id          AS user_id,
              u.nickname,
              u.external_id,
              u.channel     AS user_channel,
              u.risk_level,
              u.status      AS user_status,
              u.language,
              u.timezone,
              p.loneliness_score,
              p.vip_level,
              p.relationship_stage,
              p.chat_style,
              p.interests,
              p.forbidden_topics,
              ch.id         AS character_id,
              ch.name       AS character_name
            FROM conversations c
            LEFT JOIN users          u  ON u.id  = c.user_id
            LEFT JOIN user_profiles  p  ON p.user_id = u.id
            LEFT JOIN characters     ch ON ch.id = c.character_id
            WHERE c.id = :cid
        """),
        {"cid": conversation_id},
    )).fetchone()
    if not head_row:
        raise HTTPException(status_code=404, detail="conversation not found")

    msg_rows = (await db.execute(
        text("""
            SELECT id, sender_type, content, content_type,
                   is_operator_message, model_name, safety_result, created_at
            FROM messages
            WHERE conversation_id = :cid
            ORDER BY created_at DESC
            LIMIT 50
        """),
        {"cid": conversation_id},
    )).fetchall()

    logger.bind(
        operator_id=payload.get("sub"),
        conversation_id=conversation_id,
        messages_returned=len(msg_rows),
    ).info("admin.conversations.detail")

    return {
        "conversation": _serialize_row(head_row),
        "messages": [_serialize_row(m) for m in msg_rows],
    }


@router.delete(
    "/admin/conversations/{conversation_id}",
    summary="Admin: delete one conversation and its persisted chat history.",
)
async def admin_delete_conversation(
    conversation_id: str,
    payload: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    _require_uuid(conversation_id, "conversation_id")

    head_row = (
        await db.execute(
            text("SELECT id, user_id, channel FROM conversations WHERE id=:cid"),
            {"cid": conversation_id},
        )
    ).fetchone()
    if not head_row:
        raise HTTPException(status_code=404, detail="conversation not found")

    user_id = str(head_row[1]) if head_row[1] is not None else None
    channel = str(head_row[2]) if head_row[2] is not None else None

    try:
        await db.execute(
            text(
                """
                UPDATE memories
                SET is_active=false, updated_at=NOW()
                WHERE source_message_id IN (
                    SELECT id FROM messages WHERE conversation_id=:cid
                )
                """
            ),
            {"cid": conversation_id},
        )
        await db.execute(
            text("DELETE FROM handoff_tasks WHERE conversation_id=:cid"),
            {"cid": conversation_id},
        )
        delete_row = (
            await db.execute(
                text(
                    """
                    WITH deleted AS (
                        DELETE FROM conversations
                        WHERE id=:cid
                        RETURNING id
                    )
                    SELECT COUNT(*) AS deleted_count FROM deleted
                    """
                ),
                {"cid": conversation_id},
            )
        ).fetchone()
        deleted_count = int(delete_row[0] if delete_row else 0)
        if deleted_count == 0:
            await db.rollback()
            raise HTTPException(status_code=404, detail="conversation not found")
        await db.commit()
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise

    await _clear_deleted_message_context(user_id, [conversation_id])
    logger.bind(
        operator_id=payload.get("sub"),
        conversation_id=conversation_id,
        user_id=user_id,
        channel=channel,
        deleted_count=deleted_count,
    ).info("admin.conversations.deleted")
    return {
        "status": "success",
        "conversation_id": conversation_id,
        "user_id": user_id,
        "channel": channel,
        "deleted_count": deleted_count,
    }


@router.post(
    "/admin/conversations/{conversation_id}/operator-reply",
    summary="Admin: send an operator-confirmed reply from a conversation.",
)
async def admin_send_conversation_operator_reply(
    conversation_id: str,
    data: ConversationOperatorReplyRequest,
    request: Request,
    payload: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    _require_uuid(conversation_id, "conversation_id")
    content = (data.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")

    script_id = data.used_script_id
    if script_id:
        _require_uuid(script_id, "used_script_id")

    head_row = (
        await db.execute(
            text(
                """
                SELECT
                  c.id AS conversation_id,
                  c.channel AS conversation_channel,
                  u.id AS user_id,
                  u.channel AS user_channel,
                  u.external_id
                FROM conversations c
                JOIN users u ON u.id = c.user_id
                WHERE c.id=:cid
                """
            ),
            {"cid": conversation_id},
        )
    ).fetchone()
    if not head_row:
        raise HTTPException(status_code=404, detail="conversation not found")

    mapping = dict(head_row._mapping)
    user_id = str(mapping["user_id"])
    channel = mapping.get("conversation_channel") or mapping.get("user_channel")
    external_id = mapping.get("external_id")
    chat_id = _telegram_chat_id_from_external(str(external_id) if external_id is not None else None)
    if chat_id is None:
        raise HTTPException(
            status_code=400,
            detail="cannot resolve telegram chat_id from user external_id",
        )

    trace_id = getattr(request.state, "trace_id", None)
    operator_id = str(payload.get("sub", ""))
    msg_id = str(uuid.uuid4())

    await db.execute(
        text(
            """
            INSERT INTO messages (
              id, conversation_id, sender_type, sender_id, content, content_type,
              is_operator_message, used_script_id
            ) VALUES (
              :id, :cid, 'operator', :sid, :ct, 'text', true, :script
            )
            """
        ),
        {
            "id": msg_id,
            "cid": conversation_id,
            "sid": operator_id,
            "ct": content,
            "script": script_id,
        },
    )
    await db.execute(
        text("UPDATE conversations SET last_message_at=NOW(), updated_at=NOW() WHERE id=:id"),
        {"id": conversation_id},
    )

    sent_ok = False
    provider_message_id: str | None = None
    if channel == "telegram":
        from services.telegram_send import send_telegram_text

        sent = await send_telegram_text(
            chat_id=chat_id,
            text_content=content,
            trace_id=trace_id,
            parse_mode=None,
        )
        sent_ok = sent is not None
        provider_message_id = str(sent) if sent is not None else None
    elif channel == "telegram_real_user":
        sent_ok, provider_message_id = await _send_operator_reply_to_telegram_real_user(
            chat_id=chat_id,
            content=content,
            trace_id=trace_id,
        )
    else:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"operator reply not supported for channel={channel}",
        )

    if not sent_ok:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="telegram_send_failed",
        )

    await db.execute(
        text(
            """
            UPDATE handoff_tasks
            SET status='CLOSED', closed_at=NOW()
            WHERE conversation_id=:cid
              AND status IN ('pending', 'HUMAN_LOCKED', 'WAITING_OPERATOR')
            """
        ),
        {"cid": conversation_id},
    )
    await db.commit()

    try:
        redis = await __import__("api.messages", fromlist=["get_redis"]).get_redis()
        entry = json.dumps(
            {
                "role": "assistant",
                "content": content,
                "msg_id": msg_id,
                "ts": int(time.time()),
                "operator": True,
            },
            ensure_ascii=False,
        )
        pipe = redis.pipeline()
        pipe.rpush(f"ctx:{conversation_id}", entry)
        pipe.ltrim(f"ctx:{conversation_id}", -20, -1)
        pipe.expire(f"ctx:{conversation_id}", 86400 * 3)
        await pipe.execute()
    except Exception as exc:
        logger.bind(
            trace_id=trace_id,
            conversation_id=conversation_id,
            error_type=type(exc).__name__,
        ).warning("admin.conversations.operator_reply.redis_ctx_failed")

    logger.bind(
        trace_id=trace_id,
        operator_id=operator_id,
        conversation_id=conversation_id,
        user_id=user_id,
        channel=channel,
        message_id=msg_id,
        provider_message_id=provider_message_id,
    ).info("admin.conversations.operator_reply.sent")
    return {
        "status": "sent",
        "conversation_id": conversation_id,
        "message_id": msg_id,
        "provider_message_id": provider_message_id,
    }


@router.delete(
    "/admin/conversations/{conversation_id}/messages/{message_id}",
    summary="Admin: delete one persisted chat message from a conversation.",
)
async def admin_delete_conversation_message(
    conversation_id: str,
    message_id: str,
    payload: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    _require_uuid(conversation_id, "conversation_id")
    _require_uuid(message_id, "message_id")

    head_row = (
        await db.execute(
            text("SELECT id, user_id FROM conversations WHERE id=:cid"),
            {"cid": conversation_id},
        )
    ).fetchone()
    if not head_row:
        raise HTTPException(status_code=404, detail="conversation not found")

    user_id = str(head_row[1]) if head_row[1] is not None else None

    try:
        await db.execute(
            text(
                """
                UPDATE memories
                SET is_active=false, updated_at=NOW()
                WHERE source_message_id=:mid
                """
            ),
            {"mid": message_id},
        )
        delete_row = (
            await db.execute(
                text(
                    """
                    WITH deleted AS (
                        DELETE FROM messages
                        WHERE id=:mid AND conversation_id=:cid
                        RETURNING id
                    )
                    SELECT COUNT(*) AS deleted_count FROM deleted
                    """
                ),
                {"mid": message_id, "cid": conversation_id},
            )
        ).fetchone()
        deleted_count = int(delete_row[0] if delete_row else 0)
        if deleted_count == 0:
            await db.rollback()
            raise HTTPException(status_code=404, detail="message not found")

        await db.execute(
            text(
                """
                UPDATE conversations
                SET last_message_at = (
                    SELECT MAX(created_at)
                    FROM messages
                    WHERE conversation_id=:cid
                ),
                    updated_at = NOW()
                WHERE id=:cid
                """
            ),
            {"cid": conversation_id},
        )
        await db.commit()
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise

    await _clear_deleted_message_context(user_id, [conversation_id])
    logger.bind(
        operator_id=payload.get("sub"),
        conversation_id=conversation_id,
        message_id=message_id,
        deleted_count=deleted_count,
    ).info("admin.conversations.message_deleted")
    return {
        "status": "success",
        "conversation_id": conversation_id,
        "message_id": message_id,
        "deleted_count": deleted_count,
    }


@router.delete(
    "/admin/users/{user_id}/messages",
    summary="Admin: delete all persisted chat messages for one user.",
)
async def admin_delete_user_messages(
    user_id: str,
    payload: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    _require_uuid(user_id, "user_id")

    user_row = (
        await db.execute(text("SELECT id FROM users WHERE id=:uid"), {"uid": user_id})
    ).fetchone()
    if not user_row:
        raise HTTPException(status_code=404, detail="user not found")

    conversation_rows = (
        await db.execute(
            text("SELECT id FROM conversations WHERE user_id=:uid ORDER BY created_at DESC"),
            {"uid": user_id},
        )
    ).fetchall()
    conversation_ids = [str(row[0]) for row in conversation_rows]

    try:
        await db.execute(
            text(
                """
                UPDATE memories
                SET is_active=false, updated_at=NOW()
                WHERE user_id=:uid
                  AND source_message_id IN (
                      SELECT m.id
                      FROM messages m
                      JOIN conversations c ON c.id=m.conversation_id
                      WHERE c.user_id=:uid
                  )
                """
            ),
            {"uid": user_id},
        )
        delete_row = (
            await db.execute(
                text(
                    """
                    WITH deleted AS (
                        DELETE FROM messages
                        WHERE conversation_id IN (
                            SELECT id FROM conversations WHERE user_id=:uid
                        )
                        RETURNING id
                    )
                    SELECT COUNT(*) AS deleted_count FROM deleted
                    """
                ),
                {"uid": user_id},
            )
        ).fetchone()
        deleted_count = int(delete_row[0] if delete_row else 0)

        await db.execute(
            text(
                """
                UPDATE conversations
                SET last_message_at = NULL,
                    updated_at = NOW()
                WHERE user_id=:uid
                """
            ),
            {"uid": user_id},
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    await _clear_deleted_message_context(user_id, conversation_ids)
    logger.bind(
        operator_id=payload.get("sub"),
        user_id=user_id,
        conversation_count=len(conversation_ids),
        deleted_count=deleted_count,
    ).info("admin.users.messages_deleted")
    return {
        "status": "success",
        "user_id": user_id,
        "conversation_count": len(conversation_ids),
        "deleted_count": deleted_count,
    }


@router.get(
    "/admin/users/{user_id}",
    summary="CUR-API-01: admin user profile (user + profile + memories; operator JWT)",
)
async def admin_get_user(
    user_id: str,
    payload: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    """Admin profile payload for M1-2; same fields as data-export, requires operator JWT."""
    try:
        uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id must be a valid UUID")

    user_row = (
        await db.execute(text("SELECT * FROM users WHERE id=:uid"), {"uid": user_id})
    ).fetchone()
    if not user_row:
        raise HTTPException(status_code=404, detail="user not found")

    profile_row = (
        await db.execute(
            text("SELECT * FROM user_profiles WHERE user_id=:uid"),
            {"uid": user_id},
        )
    ).fetchone()
    memory_rows = (
        await db.execute(
            text(
                """
                SELECT id, memory_type, content, importance_score, created_at
                FROM memories
                WHERE user_id=:uid AND is_active=true
                ORDER BY importance_score DESC NULLS LAST, created_at DESC
                """
            ),
            {"uid": user_id},
        )
    ).fetchall()

    logger.bind(
        operator_id=payload.get("sub"),
        user_id=user_id,
        memories_returned=len(memory_rows),
    ).info("admin.users.detail")

    return {
        "user": _serialize_row(user_row),
        "profile": _serialize_row(profile_row) if profile_row else None,
        "memories": [_serialize_row(m) for m in memory_rows],
    }


# ── D6-3: Silent Reactivation 手动触发 ───────────────────────────────

@router.post(
    "/admin/silent-reactivation/run",
    summary="D6-3：手动触发一次静默重激活扫描（需要 operator JWT）",
)
async def admin_silent_reactivation_run(
    request: Request,
    payload: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    """对当前 DB 跑一次 silent_reactivation 扫描，返回候选/创建/跳过的汇总。

    ``SILENT_REACTIVATION_ENABLED=False`` 时立即返回零，不查 DB。
    """
    trace_id = getattr(request.state, "trace_id", None)
    summary = await run_silent_reactivation_scan(db, trace_id=trace_id)
    return {
        "enabled": settings.SILENT_REACTIVATION_ENABLED,
        "operator_id": payload.get("sub"),
        "trace_id": trace_id,
        **summary.as_dict(),
    }


# ── P4-03: 坐席看板任务管理 ───────────────────────────────────────────

@router.post(
    "/admin/handoff-tasks/{task_id}/accept",
    summary="P4-03：坐席接受任务（需要 operator JWT）",
)
async def admin_accept_handoff_task(
    task_id: str,
    payload: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    """坐席接受指定的 handoff 任务，将任务分配给当前坐席。"""
    try:
        uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="task_id must be a valid UUID")
    
    operator_id = payload.get("sub")
    
    # 检查任务是否存在且未分配
    task_row = await db.execute(
        text("""
            SELECT id, status, assigned_operator_id
            FROM handoff_tasks
            WHERE id = :task_id
        """),
        {"task_id": task_id},
    )
    task = task_row.fetchone()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task[2] is not None:  # assigned_operator_id
        raise HTTPException(status_code=400, detail="Task already assigned to another operator")
    
    # 更新任务状态
    await db.execute(
        text("""
            UPDATE handoff_tasks
            SET assigned_operator_id = :operator_id,
                status = 'HUMAN_LOCKED',
                locked_at = NOW()
            WHERE id = :task_id
        """),
        {"operator_id": operator_id, "task_id": task_id},
    )
    
    # 同时更新对应的会话状态
    await db.execute(
        text("""
            UPDATE conversations
            SET assigned_operator_id = :operator_id,
                state = 'HUMAN_LOCKED'
            WHERE id = (SELECT conversation_id FROM handoff_tasks WHERE id = :task_id)
        """),
        {"operator_id": operator_id, "task_id": task_id},
    )
    
    await db.commit()
    
    logger.bind(
        operator_id=operator_id,
        task_id=task_id,
    ).info("admin.handoff_task.accepted")
    
    return {"status": "success", "task_id": task_id, "operator_id": operator_id}


@router.post(
    "/admin/handoff-tasks/{task_id}/reject",
    summary="P4-03：坐席拒绝任务（需要 operator JWT）",
)
async def admin_reject_handoff_task(
    task_id: str,
    payload: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    """坐席拒绝指定的 handoff 任务，清除任务分配。"""
    try:
        uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="task_id must be a valid UUID")
    
    operator_id = payload.get("sub")
    
    # 检查任务是否存在
    task_row = await db.execute(
        text("""
            SELECT id, status, assigned_operator_id
            FROM handoff_tasks
            WHERE id = :task_id
        """),
        {"task_id": task_id},
    )
    task = task_row.fetchone()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # 只有任务分配给当前坐席时才能拒绝
    if task[2] != operator_id:
        raise HTTPException(status_code=400, detail="Task not assigned to current operator")
    
    # 更新任务状态
    await db.execute(
        text("""
            UPDATE handoff_tasks
            SET assigned_operator_id = NULL,
                status = 'pending',
                locked_at = NULL
            WHERE id = :task_id
        """),
        {"task_id": task_id},
    )
    
    # 同时更新对应的会话状态
    await db.execute(
        text("""
            UPDATE conversations
            SET assigned_operator_id = NULL,
                state = 'WAITING_OPERATOR'
            WHERE id = (SELECT conversation_id FROM handoff_tasks WHERE id = :task_id)
        """),
        {"task_id": task_id},
    )
    
    await db.commit()
    
    logger.bind(
        operator_id=operator_id,
        task_id=task_id,
    ).info("admin.handoff_task.rejected")
    
    return {"status": "success", "task_id": task_id, "operator_id": operator_id}
