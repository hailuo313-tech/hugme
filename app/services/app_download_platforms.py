"""Resolve third-party App download destinations."""

from __future__ import annotations

import re
from typing import Any

from loguru import logger
from sqlalchemy import text

from core.config import settings

APP_DOWNLOAD_PLATFORM_KEYS = (
    "platform_a",
    "platform_b",
    "platform_c",
    "platform_d",
    "platform_e",
    "platform_f",
)
DEFAULT_APP_DOWNLOAD_PLATFORM_KEY = "platform_a"
T1_APP_DOWNLOAD_PLATFORM_KEY = "platform_c"


def normalize_app_download_platform(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in APP_DOWNLOAD_PLATFORM_KEYS:
        return raw
    return "default"


def is_t1_app_download_country(country_code: str | None) -> bool:
    code = str(country_code or "").strip().upper()
    if len(code) != 2:
        return False
    from services.level_engine import load_t1_countries

    return code in load_t1_countries()


def _row_value(row: Any, index: int = 0, key: str | None = None) -> Any:
    if row is None:
        return None
    if hasattr(row, "_mapping") and key:
        return row._mapping.get(key)
    return row[index]


async def _user_id_for_conversation(db: Any, conversation_id: str | None) -> str | None:
    if db is None or not conversation_id:
        return None
    row = (
        await db.execute(
            text(
                """
                SELECT user_id::text
                FROM conversations
                WHERE id = CAST(:conversation_id AS uuid)
                LIMIT 1
                """
            ),
            {"conversation_id": str(conversation_id)},
        )
    ).fetchone()
    value = _row_value(row, 0, "user_id")
    return str(value) if value else None


async def _country_code_for_user(db: Any, user_id: str | None) -> str | None:
    if db is None or not user_id:
        return None
    from services.profile_intake import normalize_country_code

    row = (
        await db.execute(
            text(
                """
                SELECT country_code
                FROM user_profiles
                WHERE user_id = CAST(:user_id AS uuid)
                LIMIT 1
                """
            ),
            {"user_id": str(user_id)},
        )
    ).fetchone()
    return normalize_country_code(_row_value(row, 0, "country_code"))


async def _platform_key_for_country(db: Any, country_code: str | None) -> str | None:
    if db is None or not country_code:
        return None
    row = (
        await db.execute(
            text(
                """
                SELECT platform_key
                FROM app_download_country_routes
                WHERE country_code = :country_code
                LIMIT 1
                """
            ),
            {"country_code": country_code},
        )
    ).fetchone()
    key = normalize_app_download_platform(_row_value(row, 0, "platform_key"))
    return key if key != "default" else None


async def _country_download_url_for_country(db: Any, country_code: str | None) -> str:
    if db is None or not country_code:
        return ""
    row = (
        await db.execute(
            text(
                """
                SELECT download_url
                FROM app_download_country_routes
                WHERE country_code = :country_code
                LIMIT 1
                """
            ),
            {"country_code": country_code},
        )
    ).fetchone()
    value = _row_value(row, 0, "download_url")
    if not value:
        return ""
    return str(value).strip()


async def _account_id_for_conversation(db: Any, conversation_id: str | None) -> str | None:
    if db is None or not conversation_id:
        return None
    row = (
        await db.execute(
            text(
                """
                SELECT telegram_account_id::text
                FROM messages
                WHERE conversation_id = CAST(:conversation_id AS uuid)
                  AND telegram_account_id IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"conversation_id": str(conversation_id)},
        )
    ).fetchone()
    if row is None:
        return None
    value = row[0] if not hasattr(row, "_mapping") else row._mapping.get("telegram_account_id")
    return str(value) if value else None


async def _platform_key_for_account(db: Any, account_id: str | None) -> str:
    if db is None or not account_id:
        return "default"
    row = (
        await db.execute(
            text(
                """
                SELECT metadata->>'app_download_platform' AS platform_key
                FROM telegram_accounts
                WHERE id = CAST(:account_id AS uuid)
                LIMIT 1
                """
            ),
            {"account_id": str(account_id)},
        )
    ).fetchone()
    if row is None:
        return "default"
    value = row[0] if not hasattr(row, "_mapping") else row._mapping.get("platform_key")
    return normalize_app_download_platform(value)


async def _url_for_platform_key(db: Any, platform_key: str) -> str:
    row = (
        await db.execute(
            text(
                """
                SELECT download_url
                FROM app_download_platforms
                WHERE platform_key = :platform_key
                  AND is_active = TRUE
                LIMIT 1
                """
            ),
            {"platform_key": platform_key},
        )
    ).fetchone()
    if row is None or not row[0]:
        return ""
    return str(row[0]).strip()


async def _default_platform_url(db: Any) -> str:
    row = (
        await db.execute(
            text(
                """
                SELECT download_url
                FROM app_download_platforms
                WHERE is_active = TRUE
                ORDER BY
                    CASE WHEN platform_key = :default_key THEN 0 ELSE 1 END,
                    is_default DESC,
                    sort_order ASC,
                    updated_at DESC
                LIMIT 1
                """
            ),
            {"default_key": DEFAULT_APP_DOWNLOAD_PLATFORM_KEY},
        )
    ).fetchone()
    if row is None or not row[0]:
        return ""
    return str(row[0]).strip()


async def resolve_app_download_url(
    db: Any,
    account_id: str | None = None,
    conversation_id: str | None = None,
    user_id: str | None = None,
) -> str:
    """Resolve T1 as country URL -> C -> default; keep legacy routing for others."""
    fallback = str(settings.APP_DOWNLOAD_URL or "").strip()
    if db is None:
        return fallback
    try:
        resolved_user_id = user_id or await _user_id_for_conversation(db, conversation_id)
        country_code = await _country_code_for_user(db, resolved_user_id)
        if is_t1_app_download_country(country_code):
            country_url = await _country_download_url_for_country(db, country_code)
            if country_url:
                logger.bind(country_code=country_code, platform_key="country_route").info(
                    "app_download_platform.t1_country_url_selected"
                )
                return country_url
            t1_url = await _url_for_platform_key(db, T1_APP_DOWNLOAD_PLATFORM_KEY)
            if t1_url:
                logger.bind(
                    country_code=country_code,
                    platform_key=T1_APP_DOWNLOAD_PLATFORM_KEY,
                ).info("app_download_platform.t1_c_fallback_selected")
                return t1_url
            default_url = await _default_platform_url(db)
            if default_url:
                logger.bind(country_code=country_code, platform_key="default").info(
                    "app_download_platform.t1_default_fallback_selected"
                )
                return default_url
            return fallback
        country_key = await _platform_key_for_country(db, country_code)
        if country_key:
            country_url = await _url_for_platform_key(db, country_key)
            if country_url:
                return country_url
        bound_account_id = account_id or await _account_id_for_conversation(db, conversation_id)
        bound_key = await _platform_key_for_account(db, bound_account_id)
        if bound_key != "default":
            bound_url = await _url_for_platform_key(db, bound_key)
            if bound_url:
                return bound_url
        default_url = await _default_platform_url(db)
        if default_url:
            return default_url
    except Exception as exc:
        logger.bind(error_type=type(exc).__name__).warning("app_download_platform.resolve_failed")
    return fallback


async def resolve_app_download_url_for_country(
    db: Any,
    country_code: str | None,
    *,
    conversation_id: str | None = None,
) -> str:
    """Resolve a download URL as if the user already had this grading country."""
    from services.profile_intake import normalize_country_code

    fallback = str(settings.APP_DOWNLOAD_URL or "").strip()
    code = normalize_country_code(country_code)
    if db is None:
        return fallback
    try:
        if is_t1_app_download_country(code):
            country_url = await _country_download_url_for_country(db, code)
            if country_url:
                return country_url
            t1_url = await _url_for_platform_key(db, T1_APP_DOWNLOAD_PLATFORM_KEY)
            if t1_url:
                return t1_url
        else:
            country_key = await _platform_key_for_country(db, code)
            if country_key:
                country_url = await _url_for_platform_key(db, country_key)
                if country_url:
                    return country_url
        default_url = await _default_platform_url(db)
        if default_url:
            return default_url
        if conversation_id:
            return await resolve_app_download_url(db, conversation_id=conversation_id)
    except Exception as exc:
        logger.bind(error_type=type(exc).__name__, country_code=code).warning(
            "app_download_platform.resolve_for_country_failed"
        )
    return fallback


async def resolve_app_download_route_context(
    db: Any,
    *,
    destination_url: str = "",
    account_id: str | None = None,
    conversation_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Return the concrete route label used for attribution."""
    resolved_user_id = user_id or await _user_id_for_conversation(db, conversation_id)
    country_code = await _country_code_for_user(db, resolved_user_id)
    selected_url = str(destination_url or "").strip()
    platform_key = "default"
    if is_t1_app_download_country(country_code):
        country_url = await _country_download_url_for_country(db, country_code)
        if country_url and (not selected_url or selected_url == country_url):
            platform_key = f"country_{country_code}"
        else:
            platform_key = T1_APP_DOWNLOAD_PLATFORM_KEY
    else:
        country_key = await _platform_key_for_country(db, country_code)
        if country_key:
            platform_key = country_key
        else:
            bound_account_id = account_id or await _account_id_for_conversation(db, conversation_id)
            bound_key = await _platform_key_for_account(db, bound_account_id)
            if bound_key != "default":
                platform_key = bound_key
            else:
                row = (await db.execute(text("""
                    SELECT platform_key FROM app_download_platforms
                    WHERE is_active = TRUE
                    ORDER BY CASE WHEN platform_key = :default_key THEN 0 ELSE 1 END,
                             is_default DESC, sort_order ASC, updated_at DESC
                    LIMIT 1
                """), {"default_key": DEFAULT_APP_DOWNLOAD_PLATFORM_KEY})).fetchone()
                platform_key = str(_row_value(row, 0, "platform_key") or "default")
    if not selected_url:
        selected_url = await resolve_app_download_url(
            db, account_id=account_id, conversation_id=conversation_id, user_id=user_id
        )
    return {
        "download_url": selected_url,
        "platform_key": platform_key,
        "country_code": country_code,
        "is_t1_country": is_t1_app_download_country(country_code),
    }


async def rewrite_t1_app_download_urls_in_text(
    db: Any,
    text_value: str,
    *,
    account_id: str | None = None,
    conversation_id: str | None = None,
    user_id: str | None = None,
) -> str:
    """Replace configured or legacy App URLs with the user's current routed URL."""
    value = str(text_value or "")
    if "http" not in value:
        return value
    destination = await resolve_app_download_url(
        db, account_id=account_id, conversation_id=conversation_id, user_id=user_id
    )
    if not destination:
        return value
    rows = (await db.execute(text("SELECT download_url FROM app_download_platforms"))).fetchall()
    known_urls = {str(_row_value(row, 0, "download_url") or "").strip() for row in rows}
    known_urls.add("https://dfacgha.ofrsde.com/s/5725c4c133fee")
    known_urls.discard("")
    return re.sub(
        r"https?://[^\s<>\]\"']+",
        lambda match: destination if match.group(0).rstrip(".,!?;:)") in known_urls else match.group(0),
        value,
    )