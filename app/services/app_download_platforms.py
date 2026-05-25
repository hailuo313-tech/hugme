"""Resolve third-party App download destinations."""

from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy import text

from core.config import settings


async def resolve_app_download_url(db: Any) -> str:
    """Return the active default platform URL, falling back to APP_DOWNLOAD_URL."""
    fallback = str(settings.APP_DOWNLOAD_URL or "").strip()
    if db is None:
        return fallback
    try:
        row = (
            await db.execute(
                text(
                    """
                    SELECT download_url
                    FROM app_download_platforms
                    WHERE is_active = TRUE
                    ORDER BY is_default DESC, sort_order ASC, updated_at DESC
                    LIMIT 1
                    """
                )
            )
        ).fetchone()
        if row is not None and row[0]:
            return str(row[0]).strip()
    except Exception as exc:
        logger.bind(error_type=type(exc).__name__).warning("app_download_platform.resolve_failed")
    return fallback
