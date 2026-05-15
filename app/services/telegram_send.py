"""Outbound Telegram Bot API helpers (shared by webhook + handoff)."""
from __future__ import annotations

import httpx
from loguru import logger

from core.config import settings


async def send_telegram_text(
    *,
    chat_id: int | str,
    text_content: str,
    trace_id: str | None = None,
    parse_mode: str | None = "HTML",
) -> int | None:
    """Send a text message. Returns Telegram ``message_id`` or ``None`` on failure.

    Operator handoff replies should pass ``parse_mode=None`` so free text with
    ``<>&`` is not rejected by Telegram HTML parsing.
    """
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        logger.warning(f"[{trace_id}] tg.send.skip no_token")
        return None

    async def _post(mode: str | None) -> dict:
        payload: dict = {"chat_id": chat_id, "text": text_content}
        if mode:
            payload["parse_mode"] = mode
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json=payload,
            )
            return resp.json()

    try:
        result = await _post(parse_mode)
        if result.get("ok"):
            mid = int(result["result"]["message_id"])
            logger.info(f"[{trace_id}] tg.send.ok sent_msg_id={mid}")
            return mid
        if parse_mode:
            logger.warning(
                f"[{trace_id}] tg.send.fail mode={parse_mode} resp={result}; retry plain"
            )
            plain = await _post(None)
            if plain.get("ok"):
                mid = int(plain["result"]["message_id"])
                logger.info(f"[{trace_id}] tg.send.ok_plain sent_msg_id={mid}")
                return mid
            logger.warning(f"[{trace_id}] tg.send.fail_plain resp={plain}")
        else:
            logger.warning(f"[{trace_id}] tg.send.fail resp={result}")
    except Exception as exc:
        logger.warning(f"[{trace_id}] tg.send.error err={exc}")
    return None


def telegram_chat_id_from_external(external_id: str | None) -> int | None:
    """MVP: users.external_id is ``tg_<telegram_user_id>``; private chat_id matches user id."""
    if not external_id or not str(external_id).startswith("tg_"):
        return None
    try:
        return int(str(external_id)[3:])
    except ValueError:
        return None
