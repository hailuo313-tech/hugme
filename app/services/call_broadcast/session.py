"""Execute a single call broadcast: dial, stream video, teardown."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from loguru import logger

from core.config import settings
from services.call_broadcast.ffmpeg_pipeline import (
    ensure_playable_video,
    probe_video_duration_seconds,
    resolve_playback_duration_seconds,
)
from services.call_broadcast.pytgcalls_manager import get_pytgcalls
from services.telegram_account_manager import telegram_account_manager


async def _cache_call_peer(client: Any, chat_id: int, access_hash: int | None) -> None:
    """Prime Telethon entity cache so PyTgCalls can resolve the private chat_id."""
    from telethon.tl.functions.users import GetUsersRequest
    from telethon.tl.types import InputPeerUser, InputUser, PeerUser

    get_input_entity = getattr(client, "get_input_entity", None)
    if not callable(get_input_entity):
        raise ValueError(f"Telethon client cannot resolve entities for chat_id={chat_id}")

    if access_hash is not None:
        ah = int(access_hash)
        users = await client(
            GetUsersRequest([InputUser(user_id=int(chat_id), access_hash=ah)])
        )
        if not users:
            raise ValueError(f"GetUsersRequest returned no user for chat_id={chat_id}")
        await get_input_entity(users[0])
        return

    peer = PeerUser(user_id=int(chat_id))
    try:
        await get_input_entity(peer)
        return
    except Exception:
        pass

    get_entity = getattr(client, "get_entity", None)
    if callable(get_entity):
        entity = await get_entity(peer)
        await get_input_entity(entity)
        return

    raise ValueError(
        f"Could not cache call peer for chat_id={chat_id}; "
        "missing telegram_access_hash and entity cache lookup failed"
    )


async def reject_inbound_call(
    *,
    account_id: UUID,
    chat_id: int,
    trace_id: str | None = None,
) -> None:
    """Decline or hang up an inbound call without streaming."""
    pytgcalls = await get_pytgcalls(account_id)
    if pytgcalls is None:
        raise RuntimeError(f"no PyTgCalls for account_id={account_id}")

    log = logger.bind(
        component="call_broadcast",
        trace_id=trace_id,
        account_id=str(account_id),
        chat_id=chat_id,
    )
    for method_name in ("decline_call", "discard_call", "leave_call", "stop", "end"):
        method = getattr(pytgcalls, method_name, None)
        if not callable(method):
            continue
        try:
            result = method(int(chat_id))
            if asyncio.iscoroutine(result):
                await result
            log.bind(method=method_name).info("call_broadcast.incoming.rejected")
            return
        except TypeError:
            try:
                result = method()
                if asyncio.iscoroutine(result):
                    await result
                log.bind(method=method_name).info("call_broadcast.incoming.rejected")
                return
            except Exception:
                continue
        except Exception as exc:
            log.bind(method=method_name, error_type=type(exc).__name__).debug(
                "call_broadcast.incoming.reject_method_failed"
            )
            continue
    log.warning("call_broadcast.incoming.reject_no_method")


async def _stop_stream(pytgcalls: Any, chat_id: int) -> None:
    for method_name in ("leave_call", "stop", "end"):
        method = getattr(pytgcalls, method_name, None)
        if not callable(method):
            continue
        try:
            result = method(chat_id)
            if asyncio.iscoroutine(result):
                await result
            return
        except TypeError:
            try:
                result = method()
                if asyncio.iscoroutine(result):
                    await result
                return
            except Exception:
                continue
        except Exception as exc:
            logger.bind(chat_id=chat_id, method=method_name, error_type=type(exc).__name__).warning(
                "call_broadcast.stream.stop_failed"
            )
            return


async def run_call_broadcast(
    *,
    account_id: UUID,
    chat_id: int,
    video_path: str,
    duration_seconds: int,
    trace_id: str | None = None,
    telegram_access_hash: int | None = None,
) -> None:
    """Stream a local video file to a private Telegram peer via PyTgCalls."""
    playable = await ensure_playable_video(
        video_path,
        trace_id=trace_id,
        transcode_enabled=bool(getattr(settings, "CALL_BROADCAST_TRANSCODE_ENABLED", False)),
        work_dir=getattr(settings, "CALL_BROADCAST_WORK_DIR", "/tmp/call_broadcast"),
    )

    client = await telegram_account_manager.get_client(account_id)
    if client is None:
        raise RuntimeError(f"no connected Telethon client for account_id={account_id}")

    pytgcalls = await get_pytgcalls(account_id)
    if pytgcalls is None:
        raise RuntimeError(f"no connected Telethon client for account_id={account_id}")

    await _cache_call_peer(client, chat_id, telegram_access_hash)

    probed = await probe_video_duration_seconds(playable)
    playback_seconds = resolve_playback_duration_seconds(
        probed_seconds=probed,
        configured_seconds=duration_seconds,
        default_seconds=int(getattr(settings, "CALL_BROADCAST_DEFAULT_DURATION_SECONDS", 30)),
    )

    log = logger.bind(
        component="call_broadcast",
        trace_id=trace_id,
        account_id=str(account_id),
        chat_id=chat_id,
        playback_seconds=round(playback_seconds, 2),
        probed_seconds=round(probed, 2) if probed is not None else None,
        configured_seconds=duration_seconds,
    )
    log.info("call_broadcast.stream.start")
    try:
        play_result = pytgcalls.play(int(chat_id), playable)
        if asyncio.iscoroutine(play_result):
            await play_result
        await asyncio.sleep(playback_seconds)
    finally:
        await _stop_stream(pytgcalls, chat_id)
        log.info("call_broadcast.stream.stop")
