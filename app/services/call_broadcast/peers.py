"""Resolve Telegram peers for outbound call broadcast."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from loguru import logger

from services.telegram_account_manager import telegram_account_manager


async def _access_hash_from_client(client: Any, chat_id: int) -> int | None:
    from telethon.tl.types import PeerUser

    get_entity = getattr(client, "get_entity", None)
    if callable(get_entity):
        for candidate in (int(chat_id), PeerUser(user_id=int(chat_id))):
            try:
                entity = await get_entity(candidate)
                access_hash = getattr(entity, "access_hash", None)
                if access_hash is not None:
                    return int(access_hash)
            except Exception:
                continue

    iter_dialogs = getattr(client, "iter_dialogs", None)
    if callable(iter_dialogs):
        try:
            async for dialog in client.iter_dialogs(limit=400):
                entity = dialog.entity
                if getattr(entity, "id", None) == int(chat_id):
                    access_hash = getattr(entity, "access_hash", None)
                    if access_hash is not None:
                        return int(access_hash)
        except Exception as exc:
            logger.bind(chat_id=chat_id, error_type=type(exc).__name__).debug(
                "call_broadcast.peer.dialog_scan_failed"
            )
    return None


async def resolve_account_and_access_hash(
    *,
    chat_id: int,
    preferred_account_id: str | None,
) -> tuple[str | None, str | None]:
    """Find an active MTProto account that can reach chat_id; return (account_id, access_hash)."""
    account_ids: list[str] = []
    if preferred_account_id:
        account_ids.append(str(preferred_account_id))

    accounts = await telegram_account_manager.get_active_accounts()
    for account in accounts:
        aid = str(account.id)
        if aid not in account_ids:
            account_ids.append(aid)

    for account_id in account_ids:
        client = await telegram_account_manager.get_client(UUID(account_id))
        if client is None:
            continue
        access_hash = await _access_hash_from_client(client, chat_id)
        if access_hash is not None:
            return account_id, str(access_hash)

    return None, None
