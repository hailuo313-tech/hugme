"""One-shot phone-country backfill using live Runtime Telethon clients."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import text
from telethon.errors import FloodWaitError
from telethon.tl.types import InputPeerUser

from core.database import AsyncSessionLocal
from services.mtproto.peer_phone_country import fetch_peer_phone_country
from services.profile_intake import write_country_code
from services.telegram_account_manager import telegram_account_manager

CANDIDATE_SQL = """
WITH no_country AS (
  SELECT u.id AS user_id, u.external_id
  FROM users u
  LEFT JOIN user_profiles p ON p.user_id = u.id
  WHERE u.channel = 'telegram_real_user'
    AND COALESCE(NULLIF(BTRIM(COALESCE(p.country_code, '')), ''), '') = ''
    AND COALESCE(NULLIF(p.preferences->>'country_code', ''), '') = ''
    AND COALESCE(NULLIF(p.preferences->>'telegram_phone_country', ''), '') = ''
    AND COALESCE(p.preferences->>'telegram_phone_country_fetched', '')
        NOT IN ('true', 't', '1')
),
best_peer AS (
  SELECT DISTINCT ON (pc.user_id)
    pc.user_id,
    pc.account_id,
    pc.chat_id,
    pc.access_hash
  FROM telegram_peer_cache pc
  JOIN telegram_accounts ta ON ta.id = pc.account_id
  WHERE pc.user_id IS NOT NULL
    AND ta.status = 'connected'
  ORDER BY pc.user_id, pc.last_seen_at DESC
)
SELECT
  nc.user_id::text AS user_id,
  nc.external_id,
  bp.account_id::text AS account_id,
  bp.chat_id,
  bp.access_hash
FROM no_country nc
JOIN best_peer bp ON bp.user_id = nc.user_id
ORDER BY bp.account_id, nc.user_id
LIMIT :limit
"""

PER_ACCOUNT_GAP_SECONDS = 1.0
SAMPLE_LIMIT = 20
_backfill_task: asyncio.Task[Any] | None = None


def start_phone_country_backfill(*, dry_run: bool, limit: int) -> dict[str, Any]:
    """Run the backfill in the live Runtime event loop without blocking command polling."""
    global _backfill_task
    if _backfill_task is not None and not _backfill_task.done():
        return {"started": False, "already_running": True, "dry_run": dry_run, "limit": limit}
    _backfill_task = asyncio.create_task(
        backfill_missing_phone_countries(dry_run=dry_run, limit=limit),
        name="phone_country_backfill",
    )
    return {"started": True, "already_running": False, "dry_run": dry_run, "limit": limit}


async def backfill_missing_phone_countries(
    *,
    dry_run: bool = True,
    limit: int = 50,
) -> dict[str, Any]:
    """Detect phone-country for users who currently have no country tag."""
    limit = max(1, min(int(limit), 30000))
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(text(CANDIDATE_SQL), {"limit": limit})
        ).fetchall()

    stats: dict[str, Any] = {
        "dry_run": bool(dry_run),
        "candidates": len(rows),
        "checked": 0,
        "hit": 0,
        "empty": 0,
        "client_missing": 0,
        "errors": 0,
        "written": 0,
        "samples": [],
    }
    error_types: Counter[str] = Counter()

    for row in rows:
        data = row._mapping if hasattr(row, "_mapping") else row
        user_id = str(data["user_id"])
        account_id = str(data["account_id"])
        chat_id = int(data["chat_id"])
        access_hash = data["access_hash"]
        sample = {
            "user_id": user_id,
            "account_id": account_id,
            "chat_id": chat_id,
        }
        try:
            client = await telegram_account_manager.get_client(UUID(account_id))
            if client is None:
                stats["client_missing"] += 1
                sample["result"] = "client_missing"
                _append_sample(stats, sample)
                continue
            peer = _input_peer(chat_id, access_hash)
            parsed = await _fetch_with_flood_wait(client, peer)
            stats["checked"] += 1
            sample["phone_country"] = parsed.raw_phone_country
            sample["country_code"] = parsed.country_code
            sample["registration_month"] = parsed.registration_month
            if not parsed.country_code:
                stats["empty"] += 1
                sample["result"] = "empty"
                if not dry_run:
                    await _mark_fetched(
                        user_id,
                        registration_month=parsed.registration_month,
                        raw_phone_country=parsed.raw_phone_country,
                    )
                _append_sample(stats, sample)
            else:
                stats["hit"] += 1
                sample["result"] = "hit"
                if not dry_run:
                    await _persist_phone_country(
                        user_id,
                        country_code=parsed.country_code,
                        registration_month=parsed.registration_month,
                        raw_phone_country=parsed.raw_phone_country,
                    )
                    stats["written"] += 1
                    sample["result"] = "written"
                _append_sample(stats, sample)
        except Exception as exc:
            stats["errors"] += 1
            error_types[type(exc).__name__] += 1
            sample["result"] = type(exc).__name__
            _append_sample(stats, sample)
            logger.bind(
                user_id=user_id,
                account_id=account_id,
                chat_id=chat_id,
                error_type=type(exc).__name__,
            ).warning("mtproto.phone_country_backfill.item_failed")
        await asyncio.sleep(PER_ACCOUNT_GAP_SECONDS)

    stats["error_types"] = dict(error_types)
    logger.bind(**{k: v for k, v in stats.items() if k != "samples"}).info(
        "mtproto.phone_country_backfill.done"
    )
    return stats


def _input_peer(chat_id: int, access_hash: Any) -> Any:
    if access_hash is None or str(access_hash).strip() == "":
        return chat_id
    return InputPeerUser(user_id=int(chat_id), access_hash=int(access_hash))


async def _fetch_with_flood_wait(client: Any, peer: Any):
    try:
        return await fetch_peer_phone_country(client, peer)
    except FloodWaitError as exc:
        wait_for = int(getattr(exc, "seconds", 0) or 0) + 1
        logger.bind(seconds=wait_for).warning("mtproto.phone_country_backfill.flood_wait")
        await asyncio.sleep(wait_for)
        return await fetch_peer_phone_country(client, peer)


def _append_sample(stats: dict[str, Any], sample: dict[str, Any]) -> None:
    if len(stats["samples"]) < SAMPLE_LIMIT:
        stats["samples"].append(sample)


async def _mark_fetched(
    user_id: str,
    *,
    registration_month: str | None,
    raw_phone_country: str | None,
) -> None:
    extra = {"telegram_phone_country_fetched": True}
    if registration_month:
        extra["telegram_registration_month"] = registration_month
    if raw_phone_country:
        extra["telegram_phone_country"] = raw_phone_country
    await _merge_preferences(user_id, extra)


async def _persist_phone_country(
    user_id: str,
    *,
    country_code: str,
    registration_month: str | None,
    raw_phone_country: str | None,
) -> None:
    async with AsyncSessionLocal() as db:
        extra = {"telegram_phone_country_fetched": True}
        if registration_month:
            extra["telegram_registration_month"] = registration_month
        if raw_phone_country:
            extra["telegram_phone_country"] = raw_phone_country
        await db.execute(
            text(
                """
                UPDATE user_profiles
                SET preferences = COALESCE(preferences, '{}'::jsonb)
                    || CAST(:prefs AS jsonb),
                    updated_at = NOW()
                WHERE user_id = CAST(:uid AS uuid)
                """
            ),
            {
                "uid": user_id,
                "prefs": json.dumps(extra, ensure_ascii=False),
            },
        )
        await write_country_code(
            db,
            user_id=user_id,
            country_code=country_code,
            source="telegram_phone_country",
        )
        await db.commit()


async def _merge_preferences(user_id: str, extra: dict[str, Any]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                """
                UPDATE user_profiles
                SET preferences = COALESCE(preferences, '{}'::jsonb)
                    || CAST(:prefs AS jsonb),
                    updated_at = NOW()
                WHERE user_id = CAST(:uid AS uuid)
                """
            ),
            {"uid": user_id, "prefs": json.dumps(extra, ensure_ascii=False)},
        )
        await db.commit()
