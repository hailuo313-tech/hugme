"""
D5-1: Admin 后台 API
- POST /api/v1/admin/login  — operator 登录，返回 JWT
- GET  /api/v1/admin/me     — 验证 token，返回当前 operator 信息
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from core.database import get_db
from core.config import settings
from pydantic import BaseModel
from typing import Optional
from fastapi import Request
from loguru import logger
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
