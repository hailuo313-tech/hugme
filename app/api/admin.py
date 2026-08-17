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
from sqlalchemy import bindparam, text
from core.database import get_db
from services.dashboard_integration import sql_order_clause_for_dashboard
from core.config import settings
from pydantic import BaseModel
from typing import Any, Optional
from fastapi import Request
from loguru import logger
from decimal import Decimal
from enum import Enum
from datetime import date
import hashlib, hmac, uuid, time, json, base64, re

from services.silent_reactivation_runner import run_silent_reactivation_scan
from services.profile_intake import extract_age_from_text, normalize_country_code

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


class MessageTranslationSaveItem(BaseModel):
    id: str
    text: str


class MessageTranslationsSaveRequest(BaseModel):
    translations: list[MessageTranslationSaveItem]

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

_TELEGRAM_ACCOUNT_JOINS = """
            LEFT JOIN LATERAL (
              SELECT
                ta.id::text AS telegram_account_id,
                ta.display_name AS telegram_account_name,
                ta.phone AS telegram_account_phone,
                ta.username AS telegram_account_username
              FROM messages m
              JOIN telegram_accounts ta ON ta.id::text = m.sender_id
              WHERE m.conversation_id = c.id
                AND m.sender_type = 'assistant'
              ORDER BY m.created_at DESC
              LIMIT 1
            ) tg_acc ON TRUE
"""

_TELEGRAM_ACCOUNT_SELECT = """
              tg_acc.telegram_account_id,
              tg_acc.telegram_account_name,
              tg_acc.telegram_account_phone,
              tg_acc.telegram_account_username,
              COALESCE(
                NULLIF(tg_acc.telegram_account_name, ''),
                NULLIF(tg_acc.telegram_account_username, ''),
                NULLIF(tg_acc.telegram_account_phone, ''),
                tg_acc.telegram_account_id
              ) AS telegram_account_label
"""


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


_PROFILE_BACKFILL_MESSAGE_LIMIT = 80

_CITY_COUNTRY_ALIASES: dict[str, tuple[str, str]] = {
    "new york": ("New York", "US"),
    "nyc": ("New York", "US"),
    "los angeles": ("Los Angeles", "US"),
    "la": ("Los Angeles", "US"),
    "chicago": ("Chicago", "US"),
    "houston": ("Houston", "US"),
    "phoenix": ("Phoenix", "US"),
    "philadelphia": ("Philadelphia", "US"),
    "san antonio": ("San Antonio", "US"),
    "san diego": ("San Diego", "US"),
    "dallas": ("Dallas", "US"),
    "san jose": ("San Jose", "US"),
    "austin": ("Austin", "US"),
    "miami": ("Miami", "US"),
    "orlando": ("Orlando", "US"),
    "atlanta": ("Atlanta", "US"),
    "las vegas": ("Las Vegas", "US"),
    "seattle": ("Seattle", "US"),
    "boston": ("Boston", "US"),
    "washington": ("Washington", "US"),
    "idaho": ("Idaho", "US"),
    "wisconsin": ("Wisconsin", "US"),
    "florida": ("Florida", "US"),
    "south carolina": ("South Carolina", "US"),
    "minnesota": ("Minnesota", "US"),
    "texas": ("Texas", "US"),
    "tx": ("Texas", "US"),
    "california": ("California", "US"),
    "queens": ("Queens", "US"),
    "jamaica queens": ("Queens", "US"),
    "jamaica queen ny": ("Queens", "US"),
    "toronto": ("Toronto", "CA"),
    "vancouver": ("Vancouver", "CA"),
    "montreal": ("Montreal", "CA"),
    "calgary": ("Calgary", "CA"),
    "ottawa": ("Ottawa", "CA"),
    "london": ("London", "GB"),
    "manchester": ("Manchester", "GB"),
    "birmingham": ("Birmingham", "GB"),
    "liverpool": ("Liverpool", "GB"),
    "glasgow": ("Glasgow", "GB"),
    "berlin": ("Berlin", "DE"),
    "munich": ("Munich", "DE"),
    "hamburg": ("Hamburg", "DE"),
    "frankfurt": ("Frankfurt", "DE"),
    "cologne": ("Cologne", "DE"),
    "ibbenbüren": ("Ibbenbüren", "DE"),
    "ibbenburen": ("Ibbenbüren", "DE"),
    "paris": ("Paris", "FR"),
    "marseille": ("Marseille", "FR"),
    "lyon": ("Lyon", "FR"),
    "toulouse": ("Toulouse", "FR"),
    "toulouze": ("Toulouse", "FR"),
    "rome": ("Rome", "IT"),
    "milan": ("Milan", "IT"),
    "naples": ("Naples", "IT"),
    "madrid": ("Madrid", "ES"),
    "barcelona": ("Barcelona", "ES"),
    "valencia": ("Valencia", "ES"),
    "amsterdam": ("Amsterdam", "NL"),
    "rotterdam": ("Rotterdam", "NL"),
    "brussels": ("Brussels", "BE"),
    "zurich": ("Zurich", "CH"),
    "geneva": ("Geneva", "CH"),
    "vienna": ("Vienna", "AT"),
    "dublin": ("Dublin", "IE"),
    "copenhagen": ("Copenhagen", "DK"),
    "oslo": ("Oslo", "NO"),
    "stockholm": ("Stockholm", "SE"),
    "helsinki": ("Helsinki", "FI"),
    "reykjavik": ("Reykjavik", "IS"),
    "luxembourg": ("Luxembourg", "LU"),
    "lisbon": ("Lisbon", "PT"),
    "porto": ("Porto", "PT"),
    "athens": ("Athens", "GR"),
    "prague": ("Prague", "CZ"),
    "tokyo": ("Tokyo", "JP"),
    "osaka": ("Osaka", "JP"),
    "kyoto": ("Kyoto", "JP"),
    "sydney": ("Sydney", "AU"),
    "melbourne": ("Melbourne", "AU"),
    "brisbane": ("Brisbane", "AU"),
    "perth": ("Perth", "AU"),
    "auckland": ("Auckland", "NZ"),
    "wellington": ("Wellington", "NZ"),
    "singapore": ("Singapore", "SG"),
    "hong kong": ("Hong Kong", "HK"),
}

_PROFILE_COUNTRY_ALIASES: dict[str, str] = {
    "united states": "US",
    "usa": "US",
    "america": "US",
    "canada": "CA",
    "united kingdom": "GB",
    "uk": "GB",
    "england": "GB",
    "britain": "GB",
    "germany": "DE",
    "france": "FR",
    "italy": "IT",
    "spain": "ES",
    "netherlands": "NL",
    "holland": "NL",
    "belgium": "BE",
    "switzerland": "CH",
    "austria": "AT",
    "ireland": "IE",
    "denmark": "DK",
    "norway": "NO",
    "sweden": "SE",
    "finland": "FI",
    "iceland": "IS",
    "luxembourg": "LU",
    "portugal": "PT",
    "greece": "GR",
    "czech republic": "CZ",
    "czechia": "CZ",
    "japan": "JP",
    "australia": "AU",
    "new zealand": "NZ",
    "singapore": "SG",
    "hong kong": "HK",
    "nigeria": "NG",
}


def _has_text(value: Any) -> bool:
    return value is not None and str(value).strip() not in {"", "-"}


def _extract_city_country_from_text(content: str) -> tuple[str | None, str | None]:
    text_value = (content or "").strip()
    if not text_value:
        return None, None
    normalized = re.sub(r"\s+", " ", text_value.lower())
    for alias, (city, country_code) in _CITY_COUNTRY_ALIASES.items():
        if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", normalized):
            return city, country_code
    return None, None


def _extract_country_from_profile_text(content: str) -> str | None:
    text_value = (content or "").strip()
    if not text_value:
        return None
    normalized = re.sub(r"\s+", " ", text_value.lower())
    for alias, country_code in _PROFILE_COUNTRY_ALIASES.items():
        if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", normalized):
            return country_code

    code_context = re.search(
        r"\b(?:i am|i'm|im|am|from|in|live in|living in|based in|located in|country is|my country is)\s+(?:the\s+)?([a-z]{2})\b",
        normalized,
    )
    if code_context:
        return normalize_country_code(code_context.group(1))

    if re.fullmatch(r"[a-z]{2}", normalized):
        return normalize_country_code(normalized)
    return None


def _extract_profile_facts_from_text(content: str) -> dict[str, Any]:
    text_value = (content or "").strip()
    if not text_value:
        return {}
    city, city_country_code = _extract_city_country_from_text(text_value)
    country_code = city_country_code or _extract_country_from_profile_text(text_value)
    age = _extract_age_from_profile_text(text_value)
    return {
        "country_code": country_code,
        "city": city,
        "age": age,
    }


def _extract_age_from_profile_text(content: str) -> int | None:
    age = extract_age_from_text(content)
    if age is not None:
        return age

    normalized = re.sub(r"\s+", " ", (content or "").lower())
    leading_number = re.match(r"^(\d{1,3})(?:\s|$)", normalized)
    if leading_number and len(normalized) <= 80:
        parsed = int(leading_number.group(1))
        if 13 <= parsed <= 120:
            return parsed

    age_patterns = [
        r"\b(?:i am|i'm|im|my age is|age is|tengo|tenho|eu tenho|j'ai|j ai|ich bin|sono|ho|mi edad es)\s+(\d{1,3})\b",
        r"\b(\d{1,3})\s*(?:years old|yo|yrs old|años|anos|ans|jahre|anni|歳|才)\b",
    ]
    for pattern in age_patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        try:
            parsed = int(match.group(1))
        except (TypeError, ValueError):
            continue
        if 13 <= parsed <= 120:
            return parsed

    birth_year_match = re.search(
        r"\b(?:born in|birth year is|i was born in|naci en|nací en|nasci em|né en|geboren)\s+(19\d{2}|20\d{2})\b",
        normalized,
    )
    if birth_year_match:
        year = int(birth_year_match.group(1))
        parsed_age = date.today().year - year
        if 13 <= parsed_age <= 120:
            return parsed_age
    return None


async def _backfill_user_profile_fields_from_messages(
    db: AsyncSession,
    items: list[dict[str, Any]],
) -> None:
    """Fill missing list-only profile fields from recent user chat messages."""
    missing_by_user_id: dict[str, dict[str, bool]] = {}
    for item in items:
        user_id = str(item.get("user_id") or "").strip()
        if not user_id:
            continue
        missing = {
            "country_code": not _has_text(item.get("country_code")),
            "city": not _has_text(item.get("city")),
            "age": not _has_text(item.get("age")),
        }
        if any(missing.values()):
            missing_by_user_id[user_id] = missing

    if not missing_by_user_id:
        return

    unique_user_ids = list(missing_by_user_id.keys())
    rows = (
        await db.execute(
            text(
                """
                WITH ranked_messages AS (
                  SELECT
                    c.user_id::text AS user_id,
                    m.content,
                    ROW_NUMBER() OVER (
                      PARTITION BY c.user_id
                      ORDER BY m.created_at DESC
                    ) AS rn
                  FROM messages m
                  JOIN conversations c ON c.id = m.conversation_id
                  WHERE c.user_id::text IN :user_ids
                    AND m.sender_type = 'user'
                    AND COALESCE(m.content, '') <> ''
                )
                SELECT user_id, content
                FROM ranked_messages
                WHERE rn <= :limit
                ORDER BY user_id, rn
                """
            ).bindparams(bindparam("user_ids", expanding=True)),
            {"user_ids": unique_user_ids, "limit": _PROFILE_BACKFILL_MESSAGE_LIMIT},
        )
    ).fetchall()

    facts_by_user_id: dict[str, dict[str, Any]] = {
        user_id: {} for user_id in unique_user_ids
    }
    for row in rows:
        user_id = str(row[0])
        facts = _extract_profile_facts_from_text(str(row[1] or ""))
        existing = facts_by_user_id.setdefault(user_id, {})
        for key, value in facts.items():
            if key in existing or not _has_text(value):
                continue
            if not missing_by_user_id.get(user_id, {}).get(key):
                continue
            existing[key] = str(value)

    item_by_user_id = {
        str(item.get("user_id")): item
        for item in items
        if item.get("user_id") is not None
    }
    filled = 0
    for user_id, facts in facts_by_user_id.items():
        item = item_by_user_id.get(user_id)
        if not item:
            continue
        for key, value in facts.items():
            if _has_text(item.get(key)):
                continue
            item[key] = value
            filled += 1

    logger.bind(users=len(unique_user_ids), fields_filled=filled).info(
        "admin.users.profile_fields_backfilled_from_messages"
    )


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


def _require_uuid(value: str, field_name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError):
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
    account_id: str | None = None,
    access_hash: int | None = None,
    db: AsyncSession | None = None,
    conversation_id: str | None = None,
    user_id: str | None = None,
) -> tuple[bool, str | None]:
    try:
        from services.mtproto.human_like_send import HumanLikeSendPolicy, send_human_like_message
        from services.mtproto.peer_resolve import resolve_telethon_peer
        from services.telegram_account_manager import telegram_account_manager
        from services.telegram_peer_cache import resolve_cached_telegram_peer

        resolved_account_id = account_id
        resolved_access_hash = access_hash
        if db is not None:
            cached_peer = await resolve_cached_telegram_peer(
                db,
                conversation_id=conversation_id,
                user_id=user_id,
                account_id=resolved_account_id,
                chat_id=chat_id,
            )
            if cached_peer:
                resolved_account_id = resolved_account_id or cached_peer.get("account_id")
                if resolved_access_hash is None and cached_peer.get("access_hash") is not None:
                    resolved_access_hash = int(cached_peer["access_hash"])

        client = None
        if resolved_account_id:
            try:
                client = await telegram_account_manager.get_client(uuid.UUID(resolved_account_id))
            except (TypeError, ValueError):
                client = None
        if client is None:
            client = await telegram_account_manager.get_any_connected_client()
        if client is None:
            return False, "telegram_real_user_account_missing"

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

        peer = await resolve_telethon_peer(
            client,
            chat_id,
            access_hash=resolved_access_hash,
        )
        sent = await send_human_like_message(client, peer, content, policy=policy)

        sent_id = getattr(sent, "id", None)
        return True, str(sent_id) if sent_id is not None else None
    except Exception as exc:
        logger.bind(
            trace_id=trace_id,
            chat_id=chat_id,
            account_id=account_id,
            error_type=type(exc).__name__,
            error=str(exc)[:200],
        ).warning("admin.conversations.operator_reply.mtproto_failed")
        return False, "telegram_real_user_send_failed"


@router.get(
    "/admin/conversations",
    summary="D5-2：会话列表（分页 + state/channel/search 过滤；需要 operator JWT）",
)
async def admin_list_conversations(
    page: int = Query(1, ge=1, description="页码，1-based"),
    page_size: int = Query(20, ge=1, le=100, description="每页大小，最大 100"),
    tab: Optional[str] = Query(None, description="队列标签过滤：all/handoff/released/premium/auto/risk"),
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
    allowed_tabs = {"all", "handoff", "released", "premium", "auto", "risk"}
    tab_filter = (tab or "all").strip().lower()
    if tab_filter not in allowed_tabs:
        raise HTTPException(status_code=400, detail=f"tab must be one of {sorted(allowed_tabs)}")

    search_like = f"%{search.strip()}%" if search and search.strip() else None

    from services.post_inbound_video_expert_gate import (
        post_inbound_video_expert_only_enabled,
        post_inbound_video_expert_threshold,
        post_inbound_video_release_review_calls,
    )

    params: dict[str, Any] = {
        "state": state,
        "channel": channel,
        "search": search_like,
        "tab": tab_filter,
        "limit": page_size,
        "offset": (page - 1) * page_size,
        "expert_only_enabled": post_inbound_video_expert_only_enabled(),
        "expert_threshold": post_inbound_video_expert_threshold(),
        "release_review_calls": post_inbound_video_release_review_calls(),
    }

    premium_sql = """
        (
          UPPER(COALESCE(NULLIF(p.user_level, ''), '')) IN ('S', 'A')
          OR COALESCE(p.vip_level, 0) >= 2
        )
    """
    premium_tab_sql = f"""
        (
          c.state <> 'AI_ACTIVE'
          AND {premium_sql}
        )
    """
    expert_pending_sql = """
        (
          c.state IN ('WAITING_OPERATOR', 'HUMAN_LOCKED')
          AND c.post_inbound_video_expert_waived_at IS NULL
          AND EXISTS (
            SELECT 1 FROM users eu
            WHERE eu.id = c.user_id
              AND eu.external_id ~ '^tg_[0-9]+$'
              AND (
                SELECT COUNT(*) FROM telegram_inbound_call_events ice
                WHERE ice.chat_id = CASE
                  WHEN eu.external_id ~ '^tg_[0-9]+$'
                  THEN CAST(SUBSTRING(eu.external_id FROM 4) AS BIGINT)
                  ELSE NULL
                END
              ) >= :release_review_calls
          )
          AND EXISTS (
            SELECT 1
            FROM handoff_tasks ht
            WHERE ht.conversation_id = c.id
              AND ht.closed_at IS NULL
              AND ht.trigger_reason = 'post_inbound_video:auto_seq_complete'
              AND ht.status IN (
                'pending', 'PENDING', 'ESCALATED', 'HUMAN_LOCKED', 'WAITING_OPERATOR'
              )
          )
        )
    """
    not_frozen_sql = "(COALESCE(u.status, '') <> 'frozen' AND COALESCE(c.state, '') <> 'FROZEN')"
    tab_where = {
        "all": "TRUE",
        "handoff": f"""
            (
              {not_frozen_sql}
              AND c.state = 'WAITING_OPERATOR'
              AND c.assigned_operator_id IS NULL
              AND NOT {expert_pending_sql}
            )
        """,
        "released": f"""
            (
              {not_frozen_sql}
              AND NOT {premium_sql}
              AND c.state <> 'AI_ACTIVE'
              AND (
                c.post_inbound_video_expert_waived_at IS NOT NULL
                OR {expert_pending_sql}
              )
            )
        """,
        "premium": f"({not_frozen_sql} AND {premium_tab_sql})",
        "auto": f"({not_frozen_sql} AND c.state = 'AI_ACTIVE')",
        "risk": "(u.risk_level IN ('critical', 'high', 'elevated') OR u.status = 'frozen' OR c.state = 'FROZEN')",
    }[tab_filter]

    where = f"""
        WHERE (CAST(:state   AS TEXT) IS NULL OR c.state   = :state)
          AND (CAST(:channel AS TEXT) IS NULL OR c.channel = :channel)
          AND (CAST(:search  AS TEXT) IS NULL OR u.nickname ILIKE :search OR u.external_id ILIKE :search)
          AND ({tab_where})
    """

    total_row = (await db.execute(
        text(f"""
            SELECT COUNT(*)
            FROM conversations c
            LEFT JOIN users u ON u.id = c.user_id
            LEFT JOIN user_profiles p ON p.user_id = u.id
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
              c.post_inbound_video_expert_waived_at,
              (
                c.state IN ('WAITING_OPERATOR', 'HUMAN_LOCKED')
                AND c.post_inbound_video_expert_waived_at IS NULL
                AND EXISTS (
                  SELECT 1
                  FROM telegram_inbound_call_events ice
                  WHERE ice.chat_id = CASE
                    WHEN u.external_id ~ '^tg_[0-9]+$'
                    THEN CAST(SUBSTRING(u.external_id FROM 4) AS BIGINT)
                    ELSE NULL
                  END
                  GROUP BY ice.chat_id
                  HAVING COUNT(*) >= :release_review_calls
                )
                AND EXISTS (
                  SELECT 1
                  FROM handoff_tasks ht
                  WHERE ht.conversation_id = c.id
                    AND ht.closed_at IS NULL
                    AND ht.trigger_reason = 'post_inbound_video:auto_seq_complete'
                    AND ht.status IN (
                      'pending', 'PENDING', 'ESCALATED', 'HUMAN_LOCKED', 'WAITING_OPERATOR'
                    )
                )
              ) AS post_inbound_video_expert_release_eligible,
              (
                CAST(:expert_only_enabled AS BOOLEAN)
                AND c.post_inbound_video_expert_waived_at IS NOT NULL
                AND u.external_id LIKE 'tg_%'
                AND (
                  SELECT COUNT(*)
                  FROM call_broadcast_jobs j
                  WHERE j.chat_id = CAST(SUBSTRING(u.external_id FROM 4) AS BIGINT)
                    AND j.trigger_source = 'inbound_call'
                    AND j.status = 'completed'
                    AND COALESCE(j.metadata->>'source', '') = 'incoming_auto_answer'
                ) >= :expert_threshold
              ) AS post_inbound_video_expert_relock_eligible,
              u.id          AS user_id,
              u.nickname,
              u.external_id,
              u.channel     AS user_channel,
              u.risk_level,
              u.status      AS user_status,
              COALESCE(
                NULLIF(p.country_code, ''),
                NULLIF(p.preferences->>'country_code', ''),
                NULLIF(p.preferences->>'country', ''),
                NULLIF(p.preferences->>'geo_country', ''),
                NULLIF(p.preferences->>'ip_country', '')
              ) AS country_code,
              COALESCE(
                NULLIF(p.preferences->>'current_city', ''),
                NULLIF(p.preferences->>'city', ''),
                NULLIF(p.preferences->>'user_city', ''),
                NULLIF(p.preferences->>'location', '')
              ) AS city,
              COALESCE(
                NULLIF(p.preferences->>'age', ''),
                NULLIF(p.preferences->>'ai_extracted_age', '')
              ) AS age,
              p.loneliness_score,
              p.vip_level,
              p.user_level,
              p.chat_route,
              p.relationship_stage,
              ch.id         AS character_id,
              ch.name       AS character_name,
              first_system_message.first_system_message_at,
              latest_message.latest_message_at,
              latest_message.latest_message_sender,
              latest_message.latest_message_content,
              CASE
                WHEN latest_message.latest_message_sender = 'user' THEN 'unread'
                WHEN latest_message.latest_message_sender IS NOT NULL THEN 'read'
                ELSE NULL
              END AS message_status,
{_TELEGRAM_ACCOUNT_SELECT}
            FROM conversations c
            LEFT JOIN users          u  ON u.id  = c.user_id
            LEFT JOIN user_profiles  p  ON p.user_id = u.id
            LEFT JOIN characters     ch ON ch.id = c.character_id
            LEFT JOIN LATERAL (
              SELECT MIN(m.created_at) AS first_system_message_at
              FROM messages m
              WHERE m.conversation_id = c.id
                AND (m.sender_type IN ('assistant', 'operator') OR m.is_operator_message IS TRUE)
            ) first_system_message ON TRUE
            LEFT JOIN LATERAL (
              SELECT
                m.created_at AS latest_message_at,
                m.sender_type AS latest_message_sender,
                m.content AS latest_message_content
              FROM messages m
              WHERE m.conversation_id = c.id
              ORDER BY m.created_at DESC
              LIMIT 1
            ) latest_message ON TRUE
{_TELEGRAM_ACCOUNT_JOINS}
            {where}
            {sql_order_clause_for_dashboard()}
            LIMIT :limit OFFSET :offset
        """),
        params,
    )).fetchall()

    items = [_serialize_row(r) for r in rows]
    await _backfill_user_profile_fields_from_messages(db, items)

    logger.bind(
        operator_id=payload.get("sub"),
        page=page, page_size=page_size,
        tab=tab_filter, state=state, channel=channel, search_hit=bool(search_like),
        total=total, returned=len(items),
    ).info("admin.conversations.list")

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get(
    "/admin/users",
    summary="运营用户列表（用户画像 + 最近会话 + 链接点击 + 视频 + 培育概览）",
)
async def admin_list_users(
    page: int = Query(1, ge=1, description="页码，1-based"),
    page_size: int = Query(50, ge=1, le=100, description="每页大小，最大 100"),
    offset: Optional[int] = Query(None, ge=0, description="可选的精确偏移量；用于首批与后续批次大小不一致的连续加载"),
    channel: Optional[str] = Query(None, description="按用户渠道过滤，如 telegram_real_user"),
    status: Optional[str] = Query(None, description="按用户状态过滤，如 active/frozen"),
    country: Optional[str] = Query(None, description="按国家/T2/T3 过滤。T1 用国家码，T2/T3 用层级"),
    search: Optional[str] = Query(None, description="按昵称 / external_id / TG 用户名模糊搜索"),
    payload: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    search_like = f"%{search.strip()}%" if search and search.strip() else None
    country_filter = country.strip().upper() if country and country.strip() else None
    country_expr = """COALESCE(
            NULLIF(p.country_code, ''),
            NULLIF(p.preferences->>'country_code', ''),
            NULLIF(p.preferences->>'country', ''),
            NULLIF(p.preferences->>'geo_country', ''),
            NULLIF(p.preferences->>'ip_country', '')
        )"""
    t1_codes = (
        "US","CA","GB","DE","FR","IT","ES","NL","BE","CH","AT","IE",
        "DK","NO","SE","FI","IS","LU","PT","GR","CZ","JP","AU","NZ","SG","HK"
    )
    t2_codes = (
        "AD","AR","BG","BH","BR","BY","CL","CO","CR","CY","DO","EC","EE","FJ","GT","HR",
        "HU","ID","IL","KW","KZ","LB","LT","LV","MO","MT","MX","MY","NC","OM","PA","PE",
        "PF","PH","PL","RO","RS","RU","SA","SI","SK","TH","TR","TW","UA","UY","VN","ZA"
    )
    t1_sql = ",".join(f"'{code}'" for code in t1_codes)
    t2_sql = ",".join(f"'{code}'" for code in t2_codes)
    known_tier_sql = ",".join(f"'{code}'" for code in (*t1_codes, *t2_codes))
    country_mode = country_filter if country_filter in {"T2", "T3"} else None
    country_code_filter = country_filter if country_filter and country_filter not in {"T2", "T3"} else None
    params: dict[str, Any] = {
        "channel": channel,
        "status": status,
        "country_mode": country_mode,
        "country_code": country_code_filter,
        "search": search_like,
        "limit": page_size,
        "offset": offset if offset is not None else (page - 1) * page_size,
    }

    where = f"""
        WHERE (CAST(:channel AS TEXT) IS NULL OR u.channel = :channel)
          AND (CAST(:status AS TEXT) IS NULL OR u.status = :status)
          AND (
            (CAST(:country_mode AS TEXT) IS NULL AND CAST(:country_code AS TEXT) IS NULL)
            OR (:country_mode = 'T2' AND {country_expr} IN ({t2_sql}))
            OR (:country_mode = 'T3' AND {country_expr} IS NOT NULL AND {country_expr} NOT IN ({known_tier_sql}))
            OR (CAST(:country_code AS TEXT) IS NOT NULL AND {country_expr} = :country_code)
          )
          AND (
            CAST(:search AS TEXT) IS NULL
            OR u.nickname ILIKE :search
            OR u.external_id ILIKE :search
            OR latest_conversation.telegram_account_username ILIKE :search
            OR latest_message.last_user_message ILIKE :search
          )
    """

    base_cte = """
        WITH latest_conversation AS (
          SELECT DISTINCT ON (c.user_id)
            c.user_id,
            c.id::text AS conversation_id,
            c.state AS conversation_state,
            c.channel AS conversation_channel,
            c.last_message_at,
            c.created_at AS conversation_created_at,
            tg_acc.telegram_account_id,
            tg_acc.telegram_account_name,
            tg_acc.telegram_account_phone,
            tg_acc.telegram_account_username,
            COALESCE(
              NULLIF(tg_acc.telegram_account_name, ''),
              NULLIF(tg_acc.telegram_account_username, ''),
              NULLIF(tg_acc.telegram_account_phone, ''),
              tg_acc.telegram_account_id
            ) AS telegram_account_label
          FROM conversations c
          LEFT JOIN LATERAL (
            SELECT
              ta.id::text AS telegram_account_id,
              ta.display_name AS telegram_account_name,
              ta.phone AS telegram_account_phone,
              ta.username AS telegram_account_username
            FROM messages m
            JOIN telegram_accounts ta ON ta.id::text = m.sender_id
            WHERE m.conversation_id = c.id
              AND m.sender_type = 'assistant'
            ORDER BY m.created_at DESC
            LIMIT 1
          ) tg_acc ON TRUE
          ORDER BY c.user_id, c.last_message_at DESC NULLS LAST, c.created_at DESC
        ),
        message_stats AS (
          SELECT
            c.user_id,
            COUNT(*) FILTER (WHERE m.sender_type = 'user') AS user_messages,
            COUNT(*) FILTER (WHERE m.sender_type = 'assistant') AS ai_messages,
            COUNT(*) FILTER (WHERE m.is_operator_message IS TRUE OR m.sender_type = 'operator') AS operator_messages,
            MAX(m.created_at) AS last_any_message_at
          FROM messages m
          JOIN conversations c ON c.id = m.conversation_id
          GROUP BY c.user_id
        ),
        latest_message AS (
          SELECT
            c.user_id,
            (ARRAY_AGG(lm.content ORDER BY lm.created_at DESC) FILTER (WHERE lm.sender_type = 'user'))[1] AS last_user_message,
            (ARRAY_AGG(lm.content ORDER BY lm.created_at DESC) FILTER (WHERE lm.sender_type IN ('assistant', 'operator')))[1] AS last_system_message
          FROM messages lm
          JOIN conversations c ON c.id = lm.conversation_id
          GROUP BY c.user_id
        ),
        link_stats AS (
          SELECT
            COALESCE(e.user_id, l.user_id) AS user_id,
            COUNT(*) FILTER (WHERE e.event_type = 'link_exposed') AS link_exposures,
            COUNT(*) FILTER (WHERE e.event_type = 'click') AS link_clicks,
            MIN(e.created_at) FILTER (WHERE e.event_type = 'link_exposed') AS first_link_sent_at,
            MIN(e.created_at) FILTER (WHERE e.event_type = 'click') AS first_link_click_at,
            MAX(e.created_at) FILTER (WHERE e.event_type = 'click') AS last_link_click_at
          FROM attribution_events e
          LEFT JOIN attribution_links l ON l.tracking_id = e.tracking_id
          WHERE COALESCE(e.user_id, l.user_id) IS NOT NULL
          GROUP BY COALESCE(e.user_id, l.user_id)
        ),
        video_stats AS (
          SELECT
            COALESCE(
              CASE WHEN j.user_id ~* '^[0-9a-f-]{36}$' THEN j.user_id::uuid ELSE NULL END,
              u.id
            ) AS user_id,
            COUNT(*) AS video_calls,
            COUNT(*) FILTER (WHERE j.status = 'completed') AS video_completed,
            COUNT(*) FILTER (WHERE j.status IN ('failed', 'cancelled')) AS video_failed,
            COUNT(*) FILTER (
              WHERE j.trigger_source = 'inbound_call'
                AND j.status = 'completed'
                AND COALESCE(j.metadata->>'source', '') = 'incoming_auto_answer'
            ) AS auto_answered_calls,
            (ARRAY_AGG(j.status ORDER BY j.created_at DESC))[1] AS latest_video_status,
            MAX(j.created_at) AS latest_video_at
          FROM call_broadcast_jobs j
          LEFT JOIN users u ON u.external_id = 'tg_' || j.chat_id::text
          WHERE (j.user_id ~* '^[0-9a-f-]{36}$') OR u.id IS NOT NULL
          GROUP BY COALESCE(
            CASE WHEN j.user_id ~* '^[0-9a-f-]{36}$' THEN j.user_id::uuid ELSE NULL END,
            u.id
          )
        ),
        nurture_stats AS (
          SELECT
            ms.user_id::uuid AS user_id,
            COUNT(*) AS nurture_tasks,
            COUNT(*) FILTER (WHERE ms.status IN ('pending', 'queued', 'running')) AS nurture_running,
            COUNT(*) FILTER (WHERE ms.status IN ('sent', 'completed', 'done')) AS nurture_completed,
            MAX(ms.created_at) AS latest_nurture_at
          FROM message_schedules ms
          WHERE ms.user_id ~* '^[0-9a-f-]{36}$'
          GROUP BY ms.user_id::uuid
        )
    """

    total_row = (
        await db.execute(
            text(
                f"""
                {base_cte}
                SELECT COUNT(*)
                FROM users u
                LEFT JOIN user_profiles p ON p.user_id = u.id
                LEFT JOIN latest_conversation ON latest_conversation.user_id = u.id
                LEFT JOIN latest_message ON latest_message.user_id = u.id
                {where}
                """
            ),
            params,
        )
    ).fetchone()
    total = int((total_row[0] if total_row else 0) or 0)

    rows = (
        await db.execute(
            text(
                f"""
                {base_cte}
                SELECT
                  u.id::text AS user_id,
                  u.nickname,
                  u.external_id,
                  u.channel,
                  u.language,
                  u.status AS user_status,
                  u.risk_level,
                  u.is_minor_suspected,
                  u.created_at AS first_seen_at,
                  u.updated_at AS user_updated_at,
                  p.user_level,
                  p.chat_route,
                  {country_expr} AS country_code,
                  COALESCE(
                    NULLIF(p.preferences->>'current_city', ''),
                    NULLIF(p.preferences->>'city', ''),
                    NULLIF(p.preferences->>'user_city', ''),
                    NULLIF(p.preferences->>'location', '')
                  ) AS city,
                  COALESCE(
                    NULLIF(p.preferences->>'age', ''),
                    NULLIF(p.preferences->>'ai_extracted_age', '')
                  ) AS age,
                  p.relationship_stage,
                  p.vip_level,
                  p.loneliness_score,
                  latest_conversation.conversation_id,
                  latest_conversation.conversation_state,
                  latest_conversation.last_message_at,
                  latest_conversation.telegram_account_id,
                  latest_conversation.telegram_account_label,
                  latest_conversation.telegram_account_phone,
                  latest_conversation.telegram_account_username,
                  COALESCE(message_stats.user_messages, 0) AS user_messages,
                  COALESCE(message_stats.ai_messages, 0) AS ai_messages,
                  COALESCE(message_stats.operator_messages, 0) AS operator_messages,
                  latest_message.last_user_message,
                  latest_message.last_system_message,
                  COALESCE(link_stats.link_exposures, 0) AS link_exposures,
                  COALESCE(link_stats.link_clicks, 0) AS link_clicks,
                  link_stats.first_link_sent_at,
                  link_stats.first_link_click_at,
                  link_stats.last_link_click_at,
                  COALESCE(video_stats.video_calls, 0) AS video_calls,
                  COALESCE(video_stats.video_completed, 0) AS video_completed,
                  COALESCE(video_stats.video_failed, 0) AS video_failed,
                  COALESCE(video_stats.auto_answered_calls, 0) AS auto_answered_calls,
                  video_stats.latest_video_status,
                  video_stats.latest_video_at,
                  COALESCE(nurture_stats.nurture_tasks, 0) AS nurture_tasks,
                  COALESCE(nurture_stats.nurture_running, 0) AS nurture_running,
                  COALESCE(nurture_stats.nurture_completed, 0) AS nurture_completed,
                  nurture_stats.latest_nurture_at,
                  CASE WHEN {country_expr} IN ({t1_sql}) THEN true ELSE false END AS is_t1_country
                FROM users u
                LEFT JOIN user_profiles p ON p.user_id = u.id
                LEFT JOIN latest_conversation ON latest_conversation.user_id = u.id
                LEFT JOIN message_stats ON message_stats.user_id = u.id
                LEFT JOIN latest_message ON latest_message.user_id = u.id
                LEFT JOIN link_stats ON link_stats.user_id = u.id
                LEFT JOIN video_stats ON video_stats.user_id = u.id
                LEFT JOIN nurture_stats ON nurture_stats.user_id = u.id
                {where}
                ORDER BY COALESCE(latest_conversation.last_message_at, message_stats.last_any_message_at, u.updated_at, u.created_at) DESC NULLS LAST
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
    ).fetchall()

    items = [_serialize_row(r) for r in rows]
    await _backfill_user_profile_fields_from_messages(db, items)
    logger.bind(
        operator_id=payload.get("sub"),
        page=page,
        page_size=page_size,
        offset=params["offset"],
        channel=channel,
        status=status,
        country=country_filter,
        search_hit=bool(search_like),
        total=total,
        returned=len(items),
    ).info("admin.users.list")
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
        text(f"""
            SELECT
              c.id                                            AS conversation_id,
              c.state, c.handoff_count, c.channel,
              c.last_message_at, c.created_at,
              c.assigned_operator_id, c.ai_model_used,
              c.post_inbound_video_expert_waived_at,
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
              p.user_level,
              p.chat_route,
              p.relationship_stage,
              p.chat_style,
              p.interests,
              p.forbidden_topics,
              ch.id         AS character_id,
              ch.name       AS character_name,
{_TELEGRAM_ACCOUNT_SELECT}
            FROM conversations c
            LEFT JOIN users          u  ON u.id  = c.user_id
            LEFT JOIN user_profiles  p  ON p.user_id = u.id
            LEFT JOIN characters     ch ON ch.id = c.character_id
{_TELEGRAM_ACCOUNT_JOINS}
            WHERE c.id = :cid
        """),
        {"cid": conversation_id},
    )).fetchone()
    if not head_row:
        raise HTTPException(status_code=404, detail="conversation not found")

    msg_rows = (await db.execute(
        text("""
            SELECT id, sender_type, content, content_type,
                   is_operator_message, model_name, safety_result,
                   operator_translation_zh, created_at
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

    from services.post_inbound_video_expert_gate import (
        conversation_release_eligible,
        conversation_relock_eligible,
    )

    conversation = _serialize_row(head_row)
    conversation["post_inbound_video_expert_release_eligible"] = (
        await conversation_release_eligible(db, conversation_id)
    )
    conversation["post_inbound_video_expert_relock_eligible"] = (
        await conversation_relock_eligible(db, conversation_id)
    )

    return {
        "conversation": conversation,
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
    "/admin/conversations/{conversation_id}/join-premium-chat",
    summary="Admin: manually move one user into S/A premium chat queue.",
)
async def admin_join_premium_chat(
    conversation_id: str,
    payload: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    _require_uuid(conversation_id, "conversation_id")
    row = (
        await db.execute(
            text(
                """
                SELECT c.id, c.user_id, u.external_id, p.user_level
                FROM conversations c
                JOIN users u ON u.id = c.user_id
                LEFT JOIN user_profiles p ON p.user_id = u.id
                WHERE c.id = CAST(:cid AS uuid)
                """
            ),
            {"cid": conversation_id},
        )
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="conversation not found")

    user_id = str(row[1])
    current_level = str(row[3] or "").upper()
    next_level = "S" if current_level == "S" else "A"
    level_reason = {
        "reason": "operator_join_premium_chat",
        "operator_id": payload.get("sub"),
        "conversation_id": conversation_id,
        "previous_user_level": current_level or None,
    }
    try:
        await db.execute(
            text(
                """
                INSERT INTO user_profiles (
                    user_id, user_level, chat_route, level_reason,
                    level_updated_at, updated_at
                )
                VALUES (
                    CAST(:uid AS uuid), :user_level, 'manual_premium',
                    CAST(:level_reason AS jsonb), NOW(), NOW()
                )
                ON CONFLICT (user_id) DO UPDATE
                SET user_level = CASE
                        WHEN user_profiles.user_level = 'S' THEN 'S'
                        ELSE EXCLUDED.user_level
                    END,
                    chat_route = 'manual_premium',
                    level_reason = COALESCE(user_profiles.level_reason, '{}'::jsonb)
                        || EXCLUDED.level_reason,
                    level_updated_at = NOW(),
                    updated_at = NOW()
                """
            ),
            {
                "uid": user_id,
                "user_level": next_level,
                "level_reason": json.dumps(level_reason, ensure_ascii=False),
            },
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    logger.bind(
        operator_id=payload.get("sub"),
        conversation_id=conversation_id,
        user_id=user_id,
        previous_user_level=current_level or None,
        user_level=next_level,
        chat_route="manual_premium",
    ).info("admin.conversations.join_premium_chat")

    return {
        "status": "success",
        "conversation_id": conversation_id,
        "user_id": user_id,
        "user_level": next_level,
        "chat_route": "manual_premium",
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
                  u.external_id,
                  COALESCE(
                    (
                      SELECT m.sender_id
                      FROM messages m
                      JOIN telegram_accounts ta ON ta.id::text = m.sender_id
                      WHERE m.conversation_id = c.id
                        AND m.sender_type = 'assistant'
                      ORDER BY m.created_at DESC
                      LIMIT 1
                    ),
                    (
                      SELECT t.account_id::text
                      FROM telegram_peer_cache t
                      WHERE t.conversation_id = c.id
                      ORDER BY t.last_seen_at DESC
                      LIMIT 1
                    )
                  ) AS telegram_account_id,
                  (
                    SELECT t.access_hash
                    FROM telegram_peer_cache t
                    WHERE t.conversation_id = c.id
                    ORDER BY
                      CASE WHEN t.access_hash IS NOT NULL THEN 0 ELSE 1 END,
                      t.last_seen_at DESC
                    LIMIT 1
                  ) AS telegram_access_hash
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
    telegram_account_id = (
        str(mapping.get("telegram_account_id"))
        if mapping.get("telegram_account_id") is not None
        else None
    )
    telegram_access_hash = mapping.get("telegram_access_hash")
    if telegram_access_hash is not None:
        try:
            telegram_access_hash = int(telegram_access_hash)
        except (TypeError, ValueError):
            telegram_access_hash = None
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
            account_id=telegram_account_id,
            access_hash=telegram_access_hash,
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
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
            detail=provider_message_id or "telegram_send_failed",
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
        pipe.ltrim(f"ctx:{conversation_id}", -200, -1)
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


@router.post(
    "/admin/conversations/{conversation_id}/message-translations",
    summary="Admin: persist operator-facing translations for conversation messages.",
)
async def admin_save_conversation_message_translations(
    conversation_id: str,
    body: MessageTranslationsSaveRequest,
    payload: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    _require_uuid(conversation_id, "conversation_id")

    head_row = (
        await db.execute(
            text("SELECT id, user_id FROM conversations WHERE id=:cid"),
            {"cid": conversation_id},
        )
    ).fetchone()
    if not head_row:
        raise HTTPException(status_code=404, detail="conversation not found")
    conversation_user_id = str(head_row[1]) if head_row[1] is not None else None

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in body.translations:
        if not (item.id or "").strip():
            continue
        message_id = _require_uuid(item.id, "message_id")
        translated = (item.text or "").strip()
        if not translated or message_id in seen:
            continue
        seen.add(message_id)
        rows.append({"cid": conversation_id, "mid": message_id, "translation": translated})

    if not rows:
        return {"saved_count": 0}

    updated_ids: list[str] = []
    try:
        for row in rows:
            updated = (
                await db.execute(
                    text(
                        """
                        UPDATE messages AS m
                        SET operator_translation_zh=:translation
                        WHERE m.id=:mid
                          AND (
                            m.conversation_id=:cid
                            OR (
                              CAST(:uid AS uuid) IS NOT NULL
                              AND EXISTS (
                                SELECT 1
                                FROM conversations mc
                                WHERE mc.id = m.conversation_id
                                  AND mc.user_id = CAST(:uid AS uuid)
                              )
                            )
                          )
                        RETURNING m.id
                        """
                    ),
                    {**row, "uid": conversation_user_id},
                )
            ).fetchone()
            if updated:
                updated_ids.append(str(updated[0]))

        if not updated_ids:
            mismatch_samples: list[dict[str, str | None]] = []
            for row in rows[:5]:
                found = (
                    await db.execute(
                        text("SELECT conversation_id::text FROM messages WHERE id=:mid"),
                        {"mid": row["mid"]},
                    )
                ).fetchone()
                mismatch_samples.append(
                    {
                        "message_id": row["mid"],
                        "found_conversation_id": str(found[0]) if found else None,
                    }
                )
            await db.rollback()
            logger.bind(
                operator_id=payload.get("sub"),
                conversation_id=conversation_id,
                conversation_user_id=conversation_user_id,
                requested_count=len(rows),
                mismatch_samples=mismatch_samples,
            ).warning("admin.conversations.message_translations_no_match")
            return {"saved_count": 0, "ignored_count": len(rows)}

        await db.commit()
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise

    logger.bind(
        operator_id=payload.get("sub"),
        conversation_id=conversation_id,
        requested_count=len(rows),
        saved_count=len(updated_ids),
    ).info("admin.conversations.message_translations_saved")
    return {"saved_count": len(updated_ids)}


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
    "/admin/users/{user_id}/chat-history",
    summary="Admin: paginated complete chat history for one user.",
)
async def admin_get_user_chat_history(
    user_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
    payload: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    _require_uuid(user_id, "user_id")

    exists = (
        await db.execute(text("SELECT 1 FROM users WHERE id=:uid"), {"uid": user_id})
    ).first()
    if not exists:
        raise HTTPException(status_code=404, detail="user not found")

    total = int(
        (
            await db.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM messages m
                    JOIN conversations c ON c.id = m.conversation_id
                    WHERE c.user_id = :uid
                    """
                ),
                {"uid": user_id},
            )
        ).scalar_one()
        or 0
    )
    rows = (
        await db.execute(
            text(
                """
                SELECT
                  m.id,
                  m.conversation_id,
                  c.channel AS conversation_channel,
                  c.state AS conversation_state,
                  m.sender_type,
                  m.sender_id,
                  m.content,
                  m.content_type,
                  m.is_operator_message,
                  m.model_name,
                  m.safety_result,
                  m.operator_translation_zh,
                  m.created_at
                FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE c.user_id = :uid
                ORDER BY m.created_at DESC, m.id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {
                "uid": user_id,
                "limit": page_size,
                "offset": (page - 1) * page_size,
            },
        )
    ).fetchall()

    logger.bind(
        operator_id=payload.get("sub"),
        user_id=user_id,
        page=page,
        page_size=page_size,
        total=total,
    ).info("admin.users.chat_history")
    return {
        "items": [_serialize_row(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
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
    "/admin/conversations/{conversation_id}/accept",
    summary="Admin: accept/take over one conversation by conversation_id.",
)
async def admin_accept_conversation(
    conversation_id: str,
    payload: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    _require_uuid(conversation_id, "conversation_id")
    operator_id = payload.get("sub")

    row = (
        await db.execute(
            text(
                """
                SELECT id, assigned_operator_id
                FROM conversations
                WHERE id = CAST(:conversation_id AS uuid)
                """
            ),
            {"conversation_id": conversation_id},
        )
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="conversation not found")

    assigned_operator_id = str(row[1]) if row[1] is not None else None
    if assigned_operator_id and assigned_operator_id != str(operator_id):
        raise HTTPException(status_code=400, detail="conversation already assigned to another operator")

    await db.execute(
        text(
            """
            UPDATE handoff_tasks
            SET assigned_operator_id = CAST(:operator_id AS uuid),
                status = 'HUMAN_LOCKED',
                locked_at = NOW()
            WHERE conversation_id = CAST(:conversation_id AS uuid)
              AND status IN ('pending', 'PENDING', 'ESCALATED', 'WAITING_OPERATOR', 'HUMAN_LOCKED')
              AND (assigned_operator_id IS NULL OR assigned_operator_id = CAST(:operator_id AS uuid))
            """
        ),
        {"operator_id": operator_id, "conversation_id": conversation_id},
    )
    await db.execute(
        text(
            """
            UPDATE conversations
            SET assigned_operator_id = CAST(:operator_id AS uuid),
                state = 'HUMAN_LOCKED',
                updated_at = NOW()
            WHERE id = CAST(:conversation_id AS uuid)
            """
        ),
        {"operator_id": operator_id, "conversation_id": conversation_id},
    )
    await db.commit()

    logger.bind(
        operator_id=operator_id,
        conversation_id=conversation_id,
    ).info("admin.conversation.accepted")

    return {"status": "success", "conversation_id": conversation_id, "operator_id": operator_id}


@router.post(
    "/admin/conversations/{conversation_id}/release-human",
    summary="Admin: release a human-locked conversation back to AI.",
)
async def admin_release_human_conversation(
    conversation_id: str,
    payload: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    _require_uuid(conversation_id, "conversation_id")
    operator_id = payload.get("sub")

    updated = (
        await db.execute(
            text(
                """
                UPDATE conversations
                SET assigned_operator_id = NULL,
                    state = 'AI_ACTIVE',
                    updated_at = NOW()
                WHERE id = CAST(:conversation_id AS uuid)
                  AND (
                    state IN ('HUMAN_LOCKED', 'WAITING_OPERATOR')
                    OR assigned_operator_id IS NOT NULL
                  )
                RETURNING id
                """
            ),
            {"conversation_id": conversation_id},
        )
    ).fetchone()
    if not updated:
        raise HTTPException(status_code=400, detail="conversation not in human takeover state")

    await db.execute(
        text(
            """
            UPDATE handoff_tasks
            SET assigned_operator_id = NULL,
                status = 'CLOSED',
                closed_at = COALESCE(closed_at, NOW())
            WHERE conversation_id = CAST(:conversation_id AS uuid)
              AND status IN ('pending', 'PENDING', 'ESCALATED', 'HUMAN_LOCKED', 'WAITING_OPERATOR')
            """
        ),
        {"conversation_id": conversation_id},
    )
    from services.post_release_ai_followup import schedule_post_release_ai_checks

    queued_followup_checks = await schedule_post_release_ai_checks(
        db,
        conversation_id=conversation_id,
        source="admin_release_human",
        operator_id=str(operator_id) if operator_id else None,
    )
    await db.commit()

    logger.bind(
        operator_id=operator_id,
        conversation_id=conversation_id,
        queued_followup_checks=queued_followup_checks,
    ).info("admin.conversation.human_released")

    return {
        "status": "success",
        "conversation_id": conversation_id,
        "state": "AI_ACTIVE",
        "queued_followup_checks": queued_followup_checks,
    }


@router.post(
    "/admin/conversations/{conversation_id}/post-inbound-video-release",
    summary="放行：两段自动来电视频后的 expert-only 用户恢复 AI/话术自动回复",
)
async def admin_release_post_inbound_video_expert(
    conversation_id: str,
    payload: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    _require_uuid(conversation_id, "conversation_id")
    operator_id = payload.get("sub")
    from services.post_inbound_video_expert_gate import (
        release_post_inbound_video_expert_to_ai,
    )

    try:
        await release_post_inbound_video_expert_to_ai(
            db,
            conversation_id=conversation_id,
            operator_id=str(operator_id) if operator_id else None,
        )
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="conversation not eligible for post-inbound-video release",
        )
    from services.post_release_ai_followup import schedule_post_release_ai_checks

    queued_followup_checks = await schedule_post_release_ai_checks(
        db,
        conversation_id=conversation_id,
        source="post_inbound_video_release",
        operator_id=str(operator_id) if operator_id else None,
    )
    await db.commit()

    logger.bind(
        operator_id=operator_id,
        conversation_id=conversation_id,
        queued_followup_checks=queued_followup_checks,
    ).info("admin.conversation.post_inbound_video_released")

    return {
        "status": "success",
        "conversation_id": conversation_id,
        "state": "AI_ACTIVE",
        "queued_followup_checks": queued_followup_checks,
    }


@router.post(
    "/admin/conversations/{conversation_id}/post-inbound-video-relock",
    summary="收回人工：清除放行，恢复两段自动来电视频后的 expert-only 待人工状态",
)
async def admin_relock_post_inbound_video_expert(
    conversation_id: str,
    payload: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    _require_uuid(conversation_id, "conversation_id")
    operator_id = payload.get("sub")
    from services.post_inbound_video_expert_gate import relock_post_inbound_video_expert

    row = (
        await db.execute(
            text(
                """
                SELECT c.user_id::text AS user_id
                FROM conversations c
                WHERE c.id = CAST(:cid AS uuid)
                """
            ),
            {"cid": conversation_id},
        )
    ).fetchone()
    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="conversation not found")

    try:
        await relock_post_inbound_video_expert(
            db,
            user_id=str(row[0]),
            conversation_id=conversation_id,
            operator_id=str(operator_id) if operator_id else None,
        )
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="conversation not eligible for post-inbound-video relock",
        )

    logger.bind(
        operator_id=operator_id,
        conversation_id=conversation_id,
    ).info("admin.conversation.post_inbound_video_relocked")

    return {
        "status": "success",
        "conversation_id": conversation_id,
        "state": "WAITING_OPERATOR",
    }


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
