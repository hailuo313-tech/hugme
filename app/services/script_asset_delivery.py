"""Send media assets attached to script templates."""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger

from core.config import settings


BOT_METHOD_BY_ASSET_TYPE = {
    "image": ("sendPhoto", "photo", "upload_photo"),
    "video": ("sendVideo", "video", "upload_video"),
    "voice": ("sendVoice", "voice", "record_voice"),
    "audio": ("sendAudio", "audio", "upload_document"),
}


async def send_telegram_bot_asset(
    *,
    chat_id: int | str,
    asset: dict[str, Any],
    trace_id: str | None = None,
) -> int | None:
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        return None
    asset_type = str(asset.get("asset_type") or "").lower()
    method_info = BOT_METHOD_BY_ASSET_TYPE.get(asset_type)
    url = str(asset.get("asset_url") or "").strip()
    if not method_info or not url:
        return None
    method, field, action = method_info
    payload: dict[str, Any] = {"chat_id": chat_id, field: url}
    caption = str(asset.get("caption") or "").strip()
    if caption:
        payload["caption"] = caption
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                await client.post(
                    f"https://api.telegram.org/bot{token}/sendChatAction",
                    json={"chat_id": chat_id, "action": action},
                )
            except Exception:
                pass
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/{method}",
                json=payload,
            )
            result = resp.json()
            if result.get("ok"):
                return int(result["result"]["message_id"])
            logger.bind(
                trace_id=trace_id,
                asset_type=asset_type,
                response=result,
            ).warning("script_asset.telegram_bot_send_failed")
    except Exception as exc:
        logger.bind(
            trace_id=trace_id,
            asset_type=asset_type,
            error_type=type(exc).__name__,
        ).warning("script_asset.telegram_bot_send_error")
    return None


async def send_mtproto_asset(
    client: Any,
    peer: Any,
    asset: dict[str, Any],
    *,
    trace_id: str | None = None,
) -> Any | None:
    send_file = getattr(client, "send_file", None)
    if send_file is None:
        logger.bind(trace_id=trace_id).warning("script_asset.mtproto_no_send_file")
        return None
    url = str(asset.get("asset_url") or "").strip()
    if not url:
        return None
    caption = str(asset.get("caption") or "").strip() or None
    try:
        return await send_file(peer, url, caption=caption)
    except Exception as exc:
        logger.bind(
            trace_id=trace_id,
            asset_type=asset.get("asset_type"),
            error_type=type(exc).__name__,
        ).warning("script_asset.mtproto_send_failed")
    return None

