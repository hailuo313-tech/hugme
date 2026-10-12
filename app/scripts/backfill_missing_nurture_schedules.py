#!/usr/bin/env python3
"""Backfill nurture video-chat rounds for conversations that missed scheduling."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import text

from core.database import AsyncSessionLocal
from services.app_download_nurture import schedule_nurture_after_reply


_AFFECTED_SQL = """
WITH assistant_replies AS (
  SELECT
    c.id AS conversation_id,
    u.id AS user_id,
    u.external_id,
    m.id AS assistant_message_id,
    m.created_at AS assistant_at,
    m.sender_id AS assistant_sender_id,
    ROW_NUMBER() OVER (PARTITION BY c.id ORDER BY m.created_at DESC) AS rn
  FROM messages m
  JOIN conversations c ON c.id = m.conversation_id
  JOIN users u ON u.id = c.user_id
  WHERE m.sender_type IN ('assistant', 'ai', 'bot')
    AND u.channel = 'telegram_real_user'
    AND u.status = 'active'
    AND c.state NOT IN ('CLOSED', 'ESCALATED', 'FROZEN')
    AND u.external_id LIKE 'tg_%'
),
latest_assistant AS (
  SELECT * FROM assistant_replies WHERE rn = 1
),
has_nurture AS (
  SELECT DISTINCT metadata->>'conversation_id' AS conversation_id
  FROM message_schedules
  WHERE metadata->>'delivery_mode' = 'app_download_nurture'
    AND metadata->>'nurture_kind' = 'video_chat'
    AND status IN ('pending', 'sending', 'sent')
),
last_user_after_ai AS (
  SELECT la.conversation_id,
         MAX(um.created_at) AS last_user_at
  FROM latest_assistant la
  LEFT JOIN messages um ON um.conversation_id = la.conversation_id
    AND um.sender_type = 'user'
    AND um.created_at > la.assistant_at
  GROUP BY la.conversation_id
)
SELECT
  la.user_id::text AS user_id,
  la.external_id,
  la.conversation_id::text AS conversation_id,
  la.assistant_message_id::text AS assistant_message_id,
  la.assistant_at,
  la.assistant_sender_id,
  (
    SELECT m2.sender_id
    FROM messages m2
    WHERE m2.conversation_id = la.conversation_id
      AND m2.sender_type = 'assistant'
      AND m2.sender_id ~* '^[0-9a-f-]{36}$'
    ORDER BY m2.created_at DESC
    LIMIT 1
  ) AS fallback_account_id
FROM latest_assistant la
LEFT JOIN has_nurture hn ON hn.conversation_id = la.conversation_id::text
LEFT JOIN last_user_after_ai lua ON lua.conversation_id = la.conversation_id
WHERE hn.conversation_id IS NULL
  AND lua.last_user_at IS NULL
  AND la.assistant_at >= :cutoff_at
  AND EXISTS (
    SELECT 1
    FROM messages um
    WHERE um.conversation_id = la.conversation_id
      AND um.sender_type = 'user'
  )
  AND NOT COALESCE((
    SELECT bool_or(e.event_type = 'download')
    FROM attribution_links l
    JOIN attribution_events e ON e.tracking_id = l.tracking_id
    WHERE l.conversation_id = la.conversation_id
  ), FALSE)
ORDER BY la.assistant_at DESC
"""


def _chat_id_from_external_id(external_id: str) -> int | None:
    if not external_id.startswith("tg_"):
        return None
    raw = external_id[3:]
    return int(raw) if raw.isdigit() else None


def _account_id_from_row(row: dict) -> str | None:
    for key in ("assistant_sender_id", "fallback_account_id"):
        value = str(row.get(key) or "").strip()
        if len(value) == 36 and value.count("-") == 4:
            return value
    return None


async def _load_affected(db, *, lookback_days: int) -> list[dict]:
    cutoff_at = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).replace(tzinfo=None)
    rows = (
        await db.execute(
            text(_AFFECTED_SQL),
            {"cutoff_at": cutoff_at},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def run(*, lookback_days: int, dry_run: bool, limit: int | None) -> int:
    async with AsyncSessionLocal() as db:
        affected = await _load_affected(db, lookback_days=lookback_days)
    if limit is not None:
        affected = affected[:limit]

    print(f"affected_users={len(affected)} lookback_days={lookback_days} dry_run={dry_run}")
    if dry_run:
        for row in affected[:20]:
            print(
                f"  {row['external_id']} conv={row['conversation_id']} "
                f"assistant_at={row['assistant_at']}"
            )
        if len(affected) > 20:
            print(f"  ... and {len(affected) - 20} more")
        return 0

    queued_total = 0
    failed = 0
    skipped = 0
    for row in affected:
        chat_id = _chat_id_from_external_id(str(row["external_id"]))
        account_id = _account_id_from_row(row)
        if chat_id is None or account_id is None:
            skipped += 1
            logger.warning(
                "backfill_nurture.skip_missing_ids external_id={external_id}",
                external_id=row["external_id"],
            )
            continue
        async with AsyncSessionLocal() as db:
            try:
                queued = await schedule_nurture_after_reply(
                    db,
                    user_id=str(row["user_id"]),
                    external_user_id=str(row["external_id"]),
                    conversation_id=str(row["conversation_id"]),
                    chat_id=chat_id,
                    assistant_message_id=str(row["assistant_message_id"]),
                    trace_id="backfill-missing-nurture",
                    account_id=account_id,
                    source="reply",
                )
                queued_total += queued
                if queued == 0:
                    skipped += 1
            except Exception:
                await db.rollback()
                failed += 1
                logger.exception(
                    "backfill_nurture.failed external_id={external_id}",
                    external_id=row["external_id"],
                )

    print(
        f"done users={len(affected)} queued_rounds={queued_total} "
        f"skipped={skipped} failed={failed}"
    )
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(
        lookback_days=args.lookback_days,
        dry_run=args.dry_run,
        limit=args.limit,
    )))


if __name__ == "__main__":
    main()
