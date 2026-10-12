"""Resolve Telethon peers for scheduled / worker outbound MTProto sends."""

from __future__ import annotations

from typing import Any

from loguru import logger


async def resolve_telethon_peer(
    client: Any,
    chat_id: int,
    *,
    access_hash: int | None = None,
) -> Any:
    """Return a Telethon entity/input peer that send_message() can use."""
    from telethon.tl.functions.users import GetUsersRequest
    from telethon.tl.types import InputUser, PeerUser

    chat_id = int(chat_id)
    get_input_entity = getattr(client, "get_input_entity", None)

    if access_hash is not None and callable(get_input_entity):
        try:
            users = await client(
                GetUsersRequest(
                    [InputUser(user_id=chat_id, access_hash=int(access_hash))]
                )
            )
            if users:
                return await get_input_entity(users[0])
        except Exception as exc:
            logger.bind(
                chat_id=chat_id,
                error_type=type(exc).__name__,
            ).debug("mtproto.peer_resolve.get_users_failed")

    get_entity = getattr(client, "get_entity", None)
    if callable(get_entity):
        for candidate in (chat_id, PeerUser(user_id=chat_id)):
            try:
                entity = await get_entity(candidate)
                if callable(get_input_entity):
                    try:
                        return await get_input_entity(entity)
                    except Exception:
                        return entity
                return entity
            except Exception:
                continue

    from services.call_broadcast.peers import _access_hash_from_client

    discovered = await _access_hash_from_client(client, chat_id)
    if discovered is not None and callable(get_input_entity):
        users = await client(
            GetUsersRequest(
                [InputUser(user_id=chat_id, access_hash=int(discovered))]
            )
        )
        if users:
            return await get_input_entity(users[0])

    raise ValueError(
        f"Could not resolve Telegram peer for chat_id={chat_id}; "
        "missing access_hash and entity cache lookup failed"
    )
