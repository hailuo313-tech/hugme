from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


async def upsert_telegram_peer_cache(
    db: AsyncSession,
    *,
    user_id: str | None,
    conversation_id: str | None,
    account_id: str | None,
    chat_id: int | None,
    access_hash: int | None,
    source: str,
    trace_id: str | None = None,
    peer_metadata: dict[str, Any] | None = None,
) -> None:
    """Remember which MTProto account can reach a Telegram user."""
    if not account_id or not chat_id:
        return

    metadata = dict(peer_metadata or {})
    if trace_id:
        metadata["trace_id"] = trace_id
    if user_id:
        identity_row = (
            await db.execute(
                text(
                    """
                    SELECT UPPER(NULLIF(BTRIM(p.country_code), '')) AS country_code,
                           NULLIF(BTRIM(u.language), '') AS language,
                           NULLIF(BTRIM(u.nickname), '') AS username,
                           u.external_id,
                           EXISTS (
                             SELECT 1 FROM app_download_country_routes r
                             WHERE UPPER(r.country_code)=UPPER(p.country_code)
                           ) AS is_t1
                    FROM users u
                    LEFT JOIN user_profiles p ON p.user_id=u.id
                    WHERE u.id = CAST(:user_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"user_id": user_id},
            )
        ).mappings().first()
        metadata.setdefault("historical_user_id", str(user_id))
        metadata.setdefault("source_account_id", str(account_id))
        metadata.setdefault("captured_at", datetime.now(timezone.utc).isoformat())
        metadata["credential_ready"] = access_hash is not None
        metadata["last_verified_at"] = datetime.now(timezone.utc).isoformat()
        if identity_row:
            if identity_row.get("username"):
                metadata.setdefault("username", identity_row["username"])
            if identity_row.get("language"):
                metadata["language"] = identity_row["language"]
            if identity_row.get("external_id"):
                metadata["historical_external_user_id"] = identity_row["external_id"]
            if identity_row.get("country_code"):
                metadata["country_code"] = identity_row["country_code"]
            if identity_row.get("is_t1"):
                metadata["country_tier"] = "T1"
    await db.execute(
        text(
            """
            INSERT INTO telegram_peer_cache (
                user_id, conversation_id, account_id, chat_id, access_hash,
                source, metadata, last_seen_at, updated_at
            )
            VALUES (
                CAST(:user_id AS uuid),
                CAST(:conversation_id AS uuid),
                CAST(:account_id AS uuid),
                :chat_id,
                :access_hash,
                :source,
                CAST(:metadata AS jsonb),
                NOW(),
                NOW()
            )
            ON CONFLICT (account_id, chat_id)
            DO UPDATE SET
                user_id = COALESCE(EXCLUDED.user_id, telegram_peer_cache.user_id),
                conversation_id = COALESCE(EXCLUDED.conversation_id, telegram_peer_cache.conversation_id),
                access_hash = COALESCE(EXCLUDED.access_hash, telegram_peer_cache.access_hash),
                source = EXCLUDED.source,
                metadata = telegram_peer_cache.metadata || EXCLUDED.metadata,
                last_seen_at = NOW(),
                updated_at = NOW()
            """
        ),
        {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "account_id": account_id,
            "chat_id": int(chat_id),
            "access_hash": _safe_int(access_hash),
            "source": source,
            "metadata": json.dumps(metadata, ensure_ascii=False),
        },
    )
    logger.bind(
        trace_id=trace_id,
        account_id=account_id,
        chat_id=chat_id,
        has_access_hash=access_hash is not None,
    ).debug("telegram_peer_cache.upserted")


async def resolve_cached_telegram_peer(
    db: AsyncSession,
    *,
    conversation_id: str | None = None,
    user_id: str | None = None,
    account_id: str | None = None,
    chat_id: int | None = None,
) -> dict[str, Any] | None:
    """Return the newest cached peer for the requested dialog."""
    filters = [
        "conversation_id = COALESCE(CAST(:conversation_id AS uuid), conversation_id)",
        "user_id = COALESCE(CAST(:user_id AS uuid), user_id)",
        "chat_id = COALESCE(:chat_id, chat_id)",
    ]
    params: dict[str, Any] = {
        "conversation_id": conversation_id,
        "user_id": user_id,
        "chat_id": int(chat_id) if chat_id is not None else None,
    }
    if account_id:
        filters.append("account_id = CAST(:account_id AS uuid)")
        params["account_id"] = account_id

    sql = f"""
        SELECT account_id::text AS account_id,
               chat_id,
               access_hash,
               user_id::text AS user_id,
               conversation_id::text AS conversation_id,
               last_seen_at
        FROM telegram_peer_cache
        WHERE {' AND '.join(filters)}
        ORDER BY
          CASE WHEN access_hash IS NOT NULL THEN 0 ELSE 1 END,
          last_seen_at DESC
        LIMIT 1
    """
    try:
        row = (await db.execute(text(sql), params)).mappings().first()
    except Exception as exc:
        await db.rollback()
        logger.bind(
            error_type=type(exc).__name__,
            conversation_id=conversation_id,
            user_id=user_id,
            chat_id=chat_id,
            account_id=account_id,
        ).warning("telegram_peer_cache.resolve_failed")
        return None
    return dict(row) if row else None
