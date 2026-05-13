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

# ── Auth dependency ──────────────────────────────────────────────────

async def require_operator(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    if not creds:
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
            ORDER BY COALESCE(c.last_message_at, c.created_at) DESC
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
    try:
        uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="conversation_id must be a valid UUID")

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
