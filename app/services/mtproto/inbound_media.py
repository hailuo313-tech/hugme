"""Persist inbound Telegram photos so admin chat history can display them."""

from __future__ import annotations

import asyncio
import mimetypes
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

from core.config import settings

INBOUND_PHOTO_DIR_NAME = "inbound-photos"
INBOUND_VIDEO_DIR_NAME = "inbound-videos"
OPERATOR_MEDIA_DIR_NAME = "operator-media"
_PHOTO_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
_VIDEO_SUFFIXES = (".mp4", ".mov", ".webm", ".m4v", ".mkv", ".avi")
_AUDIO_SUFFIXES = (".mp3", ".m4a", ".ogg", ".oga", ".wav", ".aac")
_MEDIA_SUFFIXES = _PHOTO_SUFFIXES + _VIDEO_SUFFIXES + _AUDIO_SUFFIXES
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_BACKFILL_TASK: asyncio.Task | None = None


def inbound_photo_dir() -> Path:
    return Path(settings.MEDIA_UPLOAD_DIR) / INBOUND_PHOTO_DIR_NAME


def inbound_video_dir() -> Path:
    return Path(settings.MEDIA_UPLOAD_DIR) / INBOUND_VIDEO_DIR_NAME


def operator_media_dir() -> Path:
    return Path(settings.MEDIA_UPLOAD_DIR) / OPERATOR_MEDIA_DIR_NAME


def inbound_photo_stem(message_id: str) -> str:
    return str(uuid.UUID(str(message_id)))


def _find_media_in_dir(directory: Path, message_id: str, suffixes: tuple[str, ...]) -> Path | None:
    try:
        stem = inbound_photo_stem(message_id)
    except (ValueError, TypeError):
        return None
    if not directory.is_dir():
        return None
    for suffix in suffixes:
        path = directory / f"{stem}{suffix}"
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def find_inbound_photo_file(message_id: str) -> Path | None:
    return _find_media_in_dir(inbound_photo_dir(), message_id, _PHOTO_SUFFIXES)


def find_inbound_video_file(message_id: str) -> Path | None:
    return _find_media_in_dir(inbound_video_dir(), message_id, _VIDEO_SUFFIXES + _AUDIO_SUFFIXES)


def find_operator_media_file(message_id: str) -> Path | None:
    return _find_media_in_dir(operator_media_dir(), message_id, _MEDIA_SUFFIXES)


def find_chat_media_file(message_id: str) -> Path | None:
    return (
        find_inbound_photo_file(message_id)
        or find_inbound_video_file(message_id)
        or find_operator_media_file(message_id)
    )


def guess_inbound_photo_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    media_type, _ = mimetypes.guess_type(str(path))
    if media_type:
        return media_type
    if suffix in _VIDEO_SUFFIXES:
        return "video/mp4"
    if suffix in _AUDIO_SUFFIXES:
        return "audio/mpeg"
    return "image/jpeg"


def inbound_av_media_kind(message: Any) -> str | None:
    """Video/audio attachment that should be persisted for admin replay."""
    if message is None or getattr(message, "sticker", None):
        return None
    if getattr(message, "voice", None) or getattr(message, "audio", None):
        return "audio"
    if getattr(message, "video", None):
        return "video"
    document = getattr(message, "document", None)
    media = getattr(message, "media", None)
    media_document = getattr(media, "document", None)
    mime = str(
        getattr(document, "mime_type", None)
        or getattr(media_document, "mime_type", None)
        or getattr(message, "mime_type", None)
        or ""
    ).lower()
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/") and mime not in {"video/webm"}:
        return "video"
    return None


def inbound_image_media_kind(message: Any) -> str | None:
    """Image attachment that should be persisted for admin display."""
    if message is None or getattr(message, "sticker", None):
        return None
    media = getattr(message, "media", None)
    if getattr(message, "photo", None) or getattr(media, "photo", None):
        return "image"
    document = getattr(message, "document", None) or getattr(media, "document", None)
    mime = str(
        getattr(document, "mime_type", None)
        or getattr(message, "mime_type", None)
        or ""
    ).lower()
    return "image" if mime.startswith("image/") else None


def _safe_saved_path(saved: str | None, *, message_id: str) -> Path | None:
    if not saved:
        return None
    path = Path(saved)
    if not path.is_file() or path.stat().st_size <= 0:
        return None
    directory = inbound_photo_dir().resolve()
    try:
        path.resolve().relative_to(directory)
    except ValueError:
        return None
    suffix = path.suffix.lower()
    if suffix not in _PHOTO_SUFFIXES:
        target = directory / f"{inbound_photo_stem(message_id)}.jpg"
        path.replace(target)
        return target
    expected = directory / f"{inbound_photo_stem(message_id)}{suffix}"
    if path.resolve() != expected:
        if expected.exists():
            expected.unlink()
        path.replace(expected)
        return expected
    return path


async def save_inbound_telegram_photo(
    client: Any,
    telegram_message: Any,
    *,
    message_id: str,
) -> Path | None:
    """Download one inbound photo/image to MEDIA_UPLOAD_DIR/inbound-photos/{message_id}.ext."""
    if client is None or telegram_message is None:
        return None
    if not inbound_image_media_kind(telegram_message):
        return None
    existing = find_inbound_photo_file(message_id)
    if existing is not None:
        return existing

    directory = inbound_photo_dir()
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / inbound_photo_stem(message_id)
    download = getattr(client, "download_media", None)
    if not callable(download):
        return None
    try:
        saved = await asyncio.wait_for(download(telegram_message, file=str(dest)), timeout=25)
    except Exception as exc:
        logger.bind(
            message_id=message_id,
            error_type=type(exc).__name__,
        ).warning("inbound_media.download_failed")
        return None
    path = _safe_saved_path(str(saved) if saved else None, message_id=message_id)
    if path is None:
        logger.bind(message_id=message_id).warning("inbound_media.download_empty")
        return None
    logger.bind(message_id=message_id, path=str(path)).info("inbound_media.saved")
    return path


def _safe_saved_av_path(saved: str | None, *, message_id: str, kind: str) -> Path | None:
    if not saved:
        return None
    path = Path(saved)
    if not path.is_file() or path.stat().st_size <= 0:
        return None
    directory = inbound_video_dir().resolve()
    try:
        path.resolve().relative_to(directory)
    except ValueError:
        return None
    suffix = path.suffix.lower()
    allowed = _VIDEO_SUFFIXES + _AUDIO_SUFFIXES
    if suffix not in allowed:
        suffix = ".mp3" if kind == "audio" else ".mp4"
        target = directory / f"{inbound_photo_stem(message_id)}{suffix}"
        path.replace(target)
        return target
    expected = directory / f"{inbound_photo_stem(message_id)}{suffix}"
    if path.resolve() != expected:
        if expected.exists():
            expected.unlink()
        path.replace(expected)
        return expected
    return path


async def save_inbound_telegram_av(
    client: Any,
    telegram_message: Any,
    *,
    message_id: str,
    kind: str,
) -> Path | None:
    """Download inbound video/audio to MEDIA_UPLOAD_DIR/inbound-videos/{message_id}.ext."""
    if client is None or telegram_message is None or kind not in {"video", "audio"}:
        return None
    existing = find_inbound_video_file(message_id)
    if existing is not None:
        return existing

    directory = inbound_video_dir()
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / inbound_photo_stem(message_id)
    download = getattr(client, "download_media", None)
    if not callable(download):
        return None
    timeout = 120 if kind == "video" else 40
    try:
        saved = await asyncio.wait_for(download(telegram_message, file=str(dest)), timeout=timeout)
    except Exception as exc:
        logger.bind(
            message_id=message_id,
            kind=kind,
            error_type=type(exc).__name__,
        ).warning("inbound_media.av_download_failed")
        return None
    path = _safe_saved_av_path(str(saved) if saved else None, message_id=message_id, kind=kind)
    if path is None:
        logger.bind(message_id=message_id, kind=kind).warning("inbound_media.av_download_empty")
        return None
    logger.bind(message_id=message_id, kind=kind, path=str(path)).info("inbound_media.av_saved")
    return path


def _as_aware(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=_SHANGHAI).astimezone(timezone.utc)
        return value.astimezone(timezone.utc)
    return None


def _pick_matching_photo(row: dict[str, Any], photos: list[Any], used_ids: set[int]) -> Any | None:
    row_at = _as_aware(row.get("created_at"))
    best = None
    best_delta = None
    unused: list[Any] = []
    for tg_message in photos:
        tg_id = getattr(tg_message, "id", None)
        if isinstance(tg_id, int) and tg_id in used_ids:
            continue
        unused.append(tg_message)
        tg_at = _as_aware(getattr(tg_message, "date", None))
        if row_at is None or tg_at is None:
            continue
        delta = abs((row_at - tg_at).total_seconds())
        if best_delta is None or delta < best_delta:
            best = tg_message
            best_delta = delta
    if best is None and len(unused) == 1:
        return unused[0]
    if best is None or best_delta is None:
        return None
    if best_delta <= 15 * 60:
        return best
    if len(unused) == 1 and best_delta <= 7 * 24 * 3600:
        return best
    if best_delta <= 6 * 3600:
        return best
    return None


def _normalize_history(history: Any) -> list[Any]:
    if history is None:
        return []
    if isinstance(history, (list, tuple)):
        return [item for item in history if item is not None]
    return [history]


def _photo_search_filters() -> list[Any]:
    filters: list[Any] = [None]
    try:
        from telethon.tl.types import (
            InputMessagesFilterDocument,
            InputMessagesFilterPhotos,
            InputMessagesFilterPhotoVideo,
        )

        filters = [
            InputMessagesFilterPhotos(),
            InputMessagesFilterPhotoVideo(),
            InputMessagesFilterDocument(),
            None,
        ]
    except Exception:
        pass
    return filters


async def _list_inbound_photos(client: Any, peer: Any) -> list[Any]:
    collected: list[Any] = []
    seen: set[int] = set()
    for media_filter in _photo_search_filters():
        kwargs: dict[str, Any] = {"limit": 100 if media_filter is not None else 300}
        if media_filter is not None:
            kwargs["filter"] = media_filter
        try:
            history = _normalize_history(await client.get_messages(peer, **kwargs))
        except Exception as exc:
            logger.bind(
                error_type=type(exc).__name__,
                has_filter=media_filter is not None,
            ).warning("inbound_media.history_fetch_failed")
            continue
        for item in history:
            if getattr(item, "out", False):
                continue
            if not inbound_image_media_kind(item):
                continue
            tg_id = getattr(item, "id", None)
            if isinstance(tg_id, int):
                if tg_id in seen:
                    continue
                seen.add(tg_id)
            collected.append(item)
        if collected and media_filter is not None:
            break
    return collected


async def _list_photos_near_time(client: Any, peer: Any, created_at: Any) -> list[Any]:
    when = _as_aware(created_at)
    if when is None:
        return []
    try:
        history = _normalize_history(
            await client.get_messages(
                peer,
                offset_date=when + timedelta(minutes=20),
                limit=80,
            )
        )
    except Exception as exc:
        logger.bind(error_type=type(exc).__name__).warning("inbound_media.near_time_fetch_failed")
        return []
    return [
        item
        for item in history
        if item is not None
        and not getattr(item, "out", False)
        and inbound_image_media_kind(item)
    ]


def _history_sample(history: list[Any]) -> list[dict[str, Any]]:
    sample = []
    for item in history[:8]:
        media = getattr(item, "media", None)
        sample.append(
            {
                "id": getattr(item, "id", None),
                "out": bool(getattr(item, "out", False)),
                "date": str(getattr(item, "date", None)),
                "media": type(media).__name__ if media is not None else None,
                "has_photo": bool(getattr(item, "photo", None)),
            }
        )
    return sample


_MISSING_PHOTO_SQL = """
WITH photo_placeholders AS (
  SELECT
    m.id::text AS message_id,
    m.created_at,
    COALESCE(m.telegram_account_id, pc.account_id)::text AS account_id,
    COALESCE(
      pc.chat_id,
      CASE
        WHEN u.external_id ~ '^tg_[0-9]+$'
        THEN substring(u.external_id from 4)::bigint
      END
    ) AS chat_id,
    pc.access_hash
  FROM messages m
  JOIN conversations c ON c.id = m.conversation_id
  JOIN users u ON u.id = c.user_id
  LEFT JOIN LATERAL (
    SELECT account_id, chat_id, access_hash
    FROM telegram_peer_cache
    WHERE conversation_id = c.id OR user_id = u.id
    ORDER BY last_seen_at DESC
    LIMIT 1
  ) pc ON TRUE
  WHERE m.sender_type = 'user'
    AND (
      m.content IN ('[photo]', '[image]', '[media]')
      OR m.content_type IN ('image', 'photo')
    )
    AND m.created_at >= NOW() - make_interval(days => :lookback_days)
),
screenshot_msgs AS (
  SELECT DISTINCT ON (c.id)
    m.id::text AS message_id,
    m.created_at,
    COALESCE(m.telegram_account_id, pc.account_id)::text AS account_id,
    COALESCE(
      pc.chat_id,
      CASE
        WHEN u.external_id ~ '^tg_[0-9]+$'
        THEN substring(u.external_id from 4)::bigint
      END
    ) AS chat_id,
    pc.access_hash
  FROM conversations c
  JOIN users u ON u.id = c.user_id
  JOIN messages m ON m.conversation_id = c.id AND m.sender_type = 'user'
  LEFT JOIN LATERAL (
    SELECT account_id, chat_id, access_hash
    FROM telegram_peer_cache
    WHERE conversation_id = c.id OR user_id = u.id
    ORDER BY last_seen_at DESC
    LIMIT 1
  ) pc ON TRUE
  WHERE c.post_video_fixed_03_stop_reason = 'screenshot'
    AND c.post_video_fixed_03_stopped_at >= NOW() - make_interval(days => :lookback_days)
  ORDER BY c.id, LEAST(
    abs(extract(epoch FROM (m.created_at - timezone('UTC', c.post_video_fixed_03_stopped_at)))),
    abs(extract(epoch FROM (m.created_at - timezone('Asia/Shanghai', c.post_video_fixed_03_stopped_at))))
  )
)
SELECT * FROM photo_placeholders
UNION
SELECT * FROM screenshot_msgs
ORDER BY created_at DESC
LIMIT :scan_rows
"""


async def backfill_missing_inbound_photos(
    *,
    lookback_days: int = 14,
    max_rows: int = 200,
) -> dict[str, int]:
    """Pull recent [photo] placeholders from Telegram into local files."""
    from sqlalchemy import text

    from core.database import AsyncSessionLocal
    from services.mtproto.peer_resolve import resolve_telethon_peer
    from services.telegram_account_manager import telegram_account_manager

    stats = {"candidates": 0, "saved": 0, "skipped_existing": 0, "unmatched": 0, "errors": 0}
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(_MISSING_PHOTO_SQL),
                {
                    "lookback_days": int(lookback_days),
                    "scan_rows": max(2000, int(max_rows) * 10),
                },
            )
        ).mappings().all()

    pending: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for raw in rows:
        if stats["candidates"] >= int(max_rows):
            break
        row = dict(raw)
        message_id = str(row.get("message_id") or "")
        if find_inbound_photo_file(message_id) is not None:
            stats["skipped_existing"] += 1
            continue
        account_id = str(row.get("account_id") or "")
        chat_id = row.get("chat_id")
        if not message_id or not account_id or chat_id is None:
            stats["unmatched"] += 1
            continue
        stats["candidates"] += 1
        pending.setdefault((account_id, int(chat_id)), []).append(row)

    for (account_id, chat_id), group in pending.items():
        try:
            client = await telegram_account_manager.get_client(uuid.UUID(account_id))
            connected = False
            if client is not None:
                checker = getattr(client, "is_connected", None)
                connected = bool(checker() if callable(checker) else True)
            if client is None or not connected:
                stats["unmatched"] += len(group)
                logger.bind(
                    account_id=account_id,
                    chat_id=chat_id,
                    rows=len(group),
                    client_present=client is not None,
                ).warning("inbound_media.backfill_client_missing")
                continue
            access_hash = group[0].get("access_hash")
            peer = await resolve_telethon_peer(client, chat_id, access_hash=access_hash)
            photos = await _list_inbound_photos(client, peer)
            used_ids: set[int] = set()
            for row in group:
                matched = _pick_matching_photo(row, photos, used_ids)
                if matched is None:
                    near = await _list_photos_near_time(client, peer, row.get("created_at"))
                    matched = _pick_matching_photo(row, near, used_ids)
                    if matched is not None:
                        photos.extend(near)
                if matched is None:
                    stats["unmatched"] += 1
                    sample: list[dict[str, Any]] = []
                    try:
                        sample = _history_sample(
                            _normalize_history(await client.get_messages(peer, limit=8))
                        )
                    except Exception:
                        sample = []
                    logger.bind(
                        message_id=str(row.get("message_id")),
                        chat_id=chat_id,
                        photo_candidates=len(photos),
                        history_sample=sample,
                    ).warning("inbound_media.backfill_unmatched")
                    continue
                tg_id = getattr(matched, "id", None)
                if isinstance(tg_id, int):
                    used_ids.add(tg_id)
                saved = await save_inbound_telegram_photo(
                    client, matched, message_id=str(row["message_id"])
                )
                if saved is None:
                    stats["errors"] += 1
                else:
                    stats["saved"] += 1
                    async with AsyncSessionLocal() as db:
                        await db.execute(
                            text(
                                """
                                UPDATE messages
                                SET content_type = 'image'
                                WHERE id = CAST(:id AS uuid)
                                  AND (content_type IS NULL OR content_type = 'text')
                                """
                            ),
                            {"id": row["message_id"]},
                        )
                        await db.commit()
        except Exception as exc:
            stats["errors"] += len(group)
            logger.bind(
                account_id=account_id,
                chat_id=chat_id,
                error_type=type(exc).__name__,
            ).warning("inbound_media.backfill_group_failed")

    logger.bind(**stats).info("inbound_media.backfill_done")
    return stats


async def _startup_backfill_worker() -> None:
    from services.telegram_account_manager import telegram_account_manager

    await asyncio.sleep(60)
    for _ in range(18):
        if len(telegram_account_manager.clients) >= 40:
            break
        await asyncio.sleep(10)
    await asyncio.sleep(20)
    try:
        await backfill_missing_inbound_photos()
    except Exception as exc:
        logger.bind(error_type=type(exc).__name__).warning("inbound_media.startup_backfill_failed")
    while True:
        await asyncio.sleep(15 * 60)
        try:
            await backfill_missing_inbound_photos(
                lookback_days=30,
                max_rows=500,
            )
        except Exception as exc:
            logger.bind(error_type=type(exc).__name__).warning("inbound_media.periodic_backfill_failed")
    await asyncio.sleep(45)
    try:
        await backfill_missing_inbound_photos()
    except Exception as exc:
        logger.bind(error_type=type(exc).__name__).warning("inbound_media.startup_backfill_failed")


def schedule_startup_photo_backfill() -> None:
    global _BACKFILL_TASK
    if _BACKFILL_TASK is not None and not _BACKFILL_TASK.done():
        return
    _BACKFILL_TASK = asyncio.create_task(_startup_backfill_worker())
    logger.info("inbound_media.startup_backfill_scheduled")
