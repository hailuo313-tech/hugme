"""Execute a single call broadcast: dial, stream video, teardown."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from loguru import logger

from core.config import settings
from services.call_broadcast.duration import CallPlaybackResult
from services.call_broadcast.ffmpeg_pipeline import (
    ensure_post_connect_leadin_sync,
    ensure_playable_video,
    ensure_playable_video_sync,
    probe_video_duration_seconds,
    probe_video_duration_seconds_sync,
    resolve_playback_duration_seconds,
)
from services.call_broadcast.pytgcalls_manager import get_pytgcalls
from services.call_broadcast.remote_stills import (
    start_remote_still_capture,
    stop_remote_still_capture,
)
from services.telegram_account_manager import telegram_account_manager


class CallBroadcastStreamError(Exception):
    """Stream/setup failure; not an outer wall-clock ``asyncio.wait_for`` timeout."""


_playback_prepare_cache: dict[str, CallPlaybackPrepare] = {}
_playback_prepare_locks: dict[str, asyncio.Lock] = {}
_prep_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="call_prep")


def resolve_call_broadcast_work_dir() -> str:
    """Prefer a persistent cache under the video root instead of /tmp."""
    configured = str(getattr(settings, "CALL_BROADCAST_WORK_DIR", "/tmp/call_broadcast") or "").strip()
    if configured in {"", "/tmp/call_broadcast"}:
        root = str(getattr(settings, "CALL_BROADCAST_VIDEO_ROOT", "/data/videos") or "/data/videos")
        return str(Path(root) / ".call_broadcast_cache")
    return configured


def _playback_cache_key(*, video_path: str, duration_seconds: int) -> str:
    path = Path(video_path)
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        mtime_ns = 0
    transcode = bool(getattr(settings, "CALL_BROADCAST_TRANSCODE_ENABLED", False))
    return f"{path.resolve()}:{mtime_ns}:{duration_seconds}:{int(transcode)}"


def clear_playback_prepare_cache() -> None:
    _playback_prepare_cache.clear()


def peek_playback_prepare(
    *,
    video_path: str,
    duration_seconds: int,
) -> CallPlaybackPrepare | None:
    """Return a warmed playback prepare entry without blocking on ffmpeg."""
    cache_key = _playback_cache_key(
        video_path=video_path,
        duration_seconds=duration_seconds,
    )
    return _playback_prepare_cache.get(cache_key)


def _prepare_playback_sync(
    *,
    video_path: str,
    duration_seconds: int,
    trace_id: str | None,
    work_dir: str,
    transcode_enabled: bool,
) -> CallPlaybackPrepare:
    playable = ensure_playable_video_sync(
        video_path,
        trace_id=trace_id,
        transcode_enabled=transcode_enabled,
        work_dir=work_dir,
    )
    post_connect_delay = max(
        0.0,
        float(getattr(settings, "CALL_BROADCAST_POST_CONNECT_DELAY_SECONDS", 3)),
    )
    playable = ensure_post_connect_leadin_sync(
        playable,
        delay_seconds=post_connect_delay,
        work_dir=work_dir,
        trace_id=trace_id,
    )
    probed = probe_video_duration_seconds_sync(playable)
    playback_seconds = resolve_playback_duration_seconds(
        probed_seconds=probed,
        configured_seconds=duration_seconds,
        default_seconds=int(getattr(settings, "CALL_BROADCAST_DEFAULT_DURATION_SECONDS", 30)),
    )
    return CallPlaybackPrepare(
        playable_path=playable,
        playback_seconds=playback_seconds,
        probed_seconds=probed,
    )


async def warm_call_broadcast_playback_cache(
    video_paths: list[str],
    *,
    duration_seconds: int | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Pre-normalize active promo videos so inbound auto-answer prep stays fast."""
    default_seconds = int(getattr(settings, "CALL_BROADCAST_DEFAULT_DURATION_SECONDS", 30))
    warmed = 0
    errors: list[str] = []
    seen: set[str] = set()
    for raw in video_paths:
        path = str(raw or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        if not Path(path).is_file():
            errors.append(f"missing:{path}")
            continue
        try:
            await prepare_call_broadcast_playback(
                video_path=path,
                duration_seconds=duration_seconds or default_seconds,
                trace_id=trace_id,
            )
            warmed += 1
        except Exception as exc:
            errors.append(f"{path}:{type(exc).__name__}")
    return {"warmed": warmed, "errors": errors}


@dataclass(frozen=True)
class CallPlaybackPrepare:
    """Resolved media path and playback timing (prep happens outside wall clock)."""

    playable_path: str
    playback_seconds: float
    probed_seconds: float | None


def _answer_timeout_seconds() -> int:
    return int(getattr(settings, "CALL_BROADCAST_ANSWER_TIMEOUT_SECONDS", 60))


def _hangup_timeout_seconds() -> float:
    return max(2.0, float(getattr(settings, "CALL_BROADCAST_HANGUP_TIMEOUT_SECONDS", 8)))


def _still_stop_timeout_seconds() -> float:
    return max(2.0, float(getattr(settings, "CALL_BROADCAST_STILL_STOP_TIMEOUT_SECONDS", 10)))


async def _await_optional(result: Any, timeout: float) -> None:
    if asyncio.iscoroutine(result):
        await asyncio.wait_for(result, timeout=timeout)


def _playback_buffer_seconds() -> int:
    return int(getattr(settings, "CALL_BROADCAST_PLAYBACK_TIMEOUT_BUFFER_SECONDS", 90))


def _dial_teardown_buffer_seconds() -> int:
    return int(getattr(settings, "CALL_BROADCAST_DIAL_TEARDOWN_BUFFER_SECONDS", 45))


def resolve_call_broadcast_wall_timeout_seconds(playback_seconds: float | int) -> float:
    """Wall clock for dial + stream only (ffmpeg prep runs before this timer starts)."""
    playback = max(1.0, float(playback_seconds))
    derived = (
        playback
        + _answer_timeout_seconds()
        + _playback_buffer_seconds()
        + _dial_teardown_buffer_seconds()
    )

    stale_cap = resolve_stale_active_threshold_seconds(playback) - 15.0
    wall = min(derived, stale_cap)

    max_cap = int(getattr(settings, "CALL_BROADCAST_INCOMING_WALL_TIMEOUT_SECONDS", 0))
    if max_cap > 0:
        wall = min(wall, float(max_cap))

    return max(120.0, wall)


def resolve_stale_active_threshold_seconds(playback_seconds: float | int) -> float:
    """Fail-safe for jobs stuck in streaming longer than the expected wall budget."""
    playback = max(1.0, float(playback_seconds))
    min_seconds = int(getattr(settings, "CALL_BROADCAST_STALE_ACTIVE_MIN_SECONDS", 300))
    derived = (
        playback
        + _answer_timeout_seconds()
        + _playback_buffer_seconds()
        + _dial_teardown_buffer_seconds()
        + 30.0
    )
    return max(float(min_seconds), derived)


def resolve_stale_active_slack_seconds() -> int:
    """Legacy SQL helper: duration + slack covers answer, playback buffer, dial, safety."""
    return (
        _answer_timeout_seconds()
        + _playback_buffer_seconds()
        + _dial_teardown_buffer_seconds()
        + 30
    )


async def prepare_call_broadcast_playback(
    *,
    video_path: str,
    duration_seconds: int,
    trace_id: str | None = None,
) -> CallPlaybackPrepare:
    """Normalize/probe media before starting the dial+stream wall clock."""
    cache_key = _playback_cache_key(
        video_path=video_path,
        duration_seconds=duration_seconds,
    )
    cached = _playback_prepare_cache.get(cache_key)
    if cached is not None:
        return cached

    lock = _playback_prepare_locks.setdefault(cache_key, asyncio.Lock())
    async with lock:
        cached = _playback_prepare_cache.get(cache_key)
        if cached is not None:
            return cached

        work_dir = resolve_call_broadcast_work_dir()
        transcode_enabled = bool(getattr(settings, "CALL_BROADCAST_TRANSCODE_ENABLED", False))
        loop = asyncio.get_running_loop()
        prepared = await loop.run_in_executor(
            _prep_executor,
            lambda: _prepare_playback_sync(
                video_path=video_path,
                duration_seconds=duration_seconds,
                trace_id=trace_id,
                work_dir=work_dir,
                transcode_enabled=transcode_enabled,
            ),
        )
        _playback_prepare_cache[cache_key] = prepared
        logger.bind(
            trace_id=trace_id,
            video_path=video_path,
            playable_path=prepared.playable_path,
            playback_seconds=round(prepared.playback_seconds, 2),
        ).info("call_broadcast.playback.prepared")
        return prepared


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


def _pytgcalls_input_call_cache(pytgcalls: Any) -> Any | None:
    app = getattr(pytgcalls, "_app", None)
    for obj in (app, getattr(app, "_bind_client", None)):
        cache = getattr(obj, "_cache", None)
        if cache is not None and callable(getattr(cache, "set_cache", None)):
            return cache
    return None


async def _read_input_phone_call(pytgcalls: Any, chat_id: int) -> Any:
    app = getattr(pytgcalls, "_app", None)
    getter = getattr(app, "get_input_call", None)
    if not callable(getter):
        return True
    try:
        result = getter(int(chat_id))
        if asyncio.iscoroutine(result):
            result = await result
        return result
    except Exception:
        return None


async def capture_incoming_phone_call(
    pytgcalls: Any,
    chat_id: int,
    *,
    timeout_seconds: float = 2.0,
) -> Any | None:
    """Read InputPhoneCall while the inbound ring is still cached."""
    deadline = time.monotonic() + max(0.05, float(timeout_seconds))
    while True:
        peer = await _read_input_phone_call(pytgcalls, int(chat_id))
        if peer:
            return peer
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(0.05)


def restore_incoming_phone_call(pytgcalls: Any, chat_id: int, peer: Any) -> bool:
    """Re-inject a captured InputPhoneCall before accept/play."""
    if peer in (None, True, False):
        return False
    cache = _pytgcalls_input_call_cache(pytgcalls)
    if cache is None:
        return False
    try:
        cache.set_cache(int(chat_id), peer)
        return True
    except Exception:
        return False


async def _wait_for_incoming_phone_call(
    pytgcalls: Any,
    chat_id: int,
    *,
    timeout_seconds: float = 4.0,
) -> bool:
    """Wait until PyTgCalls has cached InputPhoneCall for this P2P chat."""
    peer = await capture_incoming_phone_call(
        pytgcalls,
        chat_id,
        timeout_seconds=timeout_seconds,
    )
    return bool(peer)


async def _invoke_connect(
    pytgcalls: Any,
    chat_id: int,
    playable: str,
    *,
    require_incoming_phone_call: bool = False,
) -> None:
    """Answer/dial with delayed media in one supported PyTgCalls operation."""
    from pytgcalls.types import CallConfig

    if require_incoming_phone_call:
        if not await _wait_for_incoming_phone_call(pytgcalls, int(chat_id)):
            logger.bind(chat_id=chat_id).warning(
                "call_broadcast.stream.incoming_phone_call_missing"
            )
            raise CallBroadcastStreamError(
                f"incoming phone call cache missing for chat_id={chat_id}"
            )

    answer_timeout = int(
        getattr(settings, "CALL_BROADCAST_ANSWER_TIMEOUT_SECONDS", 60)
    )
    config = CallConfig(timeout=answer_timeout)
    play_result = pytgcalls.play(int(chat_id), playable, config)
    if asyncio.iscoroutine(play_result):
        await play_result


async def hang_up_call(
    *,
    account_id: UUID | None = None,
    chat_id: int,
    trace_id: str | None = None,
    pytgcalls: Any | None = None,
) -> None:
    """Best-effort hang up for an active private video call."""
    wrapper = pytgcalls
    if wrapper is None:
        if account_id is None:
            raise ValueError("hang_up_call requires account_id or pytgcalls")
        wrapper = await get_pytgcalls(account_id)
    if wrapper is None:
        raise RuntimeError(f"no PyTgCalls for account_id={account_id}")

    log = logger.bind(
        component="call_broadcast",
        trace_id=trace_id,
        account_id=str(account_id) if account_id is not None else None,
        chat_id=chat_id,
    )
    for method_name in (
        "leave_call",
        "discard_call",
        "decline_call",
        "stop",
        "end",
    ):
        method = getattr(wrapper, method_name, None)
        if not callable(method):
            continue
        for args in ((int(chat_id),), tuple()):
            try:
                result = method(*args)
                await _await_optional(result, _hangup_timeout_seconds())
                log.bind(method=method_name).info("call_broadcast.hangup.ok")
                return
            except TypeError:
                continue
            except asyncio.TimeoutError:
                log.bind(method=method_name).warning("call_broadcast.hangup.method_timeout")
                continue
            except Exception as exc:
                log.bind(method=method_name, error_type=type(exc).__name__).debug(
                    "call_broadcast.hangup.method_failed"
                )
                continue
    log.warning("call_broadcast.hangup.no_method")


async def reject_inbound_call(
    *,
    account_id: UUID,
    chat_id: int,
    trace_id: str | None = None,
) -> None:
    """Decline or hang up an inbound call without streaming."""
    await hang_up_call(account_id=account_id, chat_id=chat_id, trace_id=trace_id)


async def _stop_stream(
    pytgcalls: Any,
    chat_id: int,
    *,
    account_id: UUID | None = None,
    trace_id: str | None = None,
) -> None:
    await hang_up_call(
        account_id=account_id,
        chat_id=chat_id,
        trace_id=trace_id,
        pytgcalls=pytgcalls,
    )


async def run_call_broadcast(
    *,
    account_id: UUID,
    chat_id: int,
    video_path: str,
    duration_seconds: int,
    trace_id: str | None = None,
    telegram_access_hash: int | None = None,
    prepared: CallPlaybackPrepare | None = None,
    pytgcalls: Any | None = None,
    job_id: str | None = None,
    require_incoming_phone_call: bool = False,
) -> CallPlaybackResult:
    """Stream a local video file to a private Telegram peer via PyTgCalls."""
    if prepared is not None:
        playable = prepared.playable_path
        probed = prepared.probed_seconds
        playback_seconds = prepared.playback_seconds
    else:
        prepared = await prepare_call_broadcast_playback(
            video_path=video_path,
            duration_seconds=duration_seconds,
            trace_id=trace_id,
        )
        playable = prepared.playable_path
        probed = prepared.probed_seconds
        playback_seconds = prepared.playback_seconds

    client = await telegram_account_manager.get_client(account_id)
    if client is None:
        raise RuntimeError(f"no connected Telethon client for account_id={account_id}")

    # For an inbound call, use the exact PyTgCalls wrapper that emitted the
    # ChatUpdate.  A freshly looked-up wrapper may not own the incoming phone
    # call cache and would incorrectly start a new outbound call instead.
    pytgcalls = pytgcalls or await get_pytgcalls(account_id)
    if pytgcalls is None:
        raise RuntimeError(f"no connected Telethon client for account_id={account_id}")

    log = logger.bind(
        component="call_broadcast",
        trace_id=trace_id,
        account_id=str(account_id),
        chat_id=chat_id,
        playback_seconds=round(playback_seconds, 2),
        probed_seconds=round(probed, 2) if probed is not None else None,
        configured_seconds=duration_seconds,
    )
    try:
        await asyncio.wait_for(
            _cache_call_peer(client, chat_id, telegram_access_hash),
            timeout=8,
        )
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning(
            "call_broadcast.stream.peer_cache_failed"
        )

    log.info("call_broadcast.stream.start")
    playback_timeout = playback_seconds + int(
        getattr(settings, "CALL_BROADCAST_PLAYBACK_TIMEOUT_BUFFER_SECONDS", 90)
    )

    wall_started = time.monotonic()
    try:
        try:
            try:
                await _invoke_connect(
                    pytgcalls,
                    int(chat_id),
                    playable,
                    require_incoming_phone_call=require_incoming_phone_call,
                )
            except asyncio.TimeoutError:
                if not require_incoming_phone_call:
                    raise
                log.warning("call_broadcast.stream.incoming_accept_retry")
                await asyncio.sleep(0.5)
                await _invoke_connect(
                    pytgcalls,
                    int(chat_id),
                    playable,
                    require_incoming_phone_call=True,
                )
        except asyncio.TimeoutError as exc:
            log.warning("call_broadcast.stream.answer_timeout")
            raise CallBroadcastStreamError(
                f"call not answered for chat_id={chat_id}"
            ) from exc
        except Exception as exc:
            if type(exc).__name__ == "TimedOutAnswer":
                log.warning("call_broadcast.stream.answer_timeout")
                raise CallBroadcastStreamError(
                    f"call not answered for chat_id={chat_id}"
                ) from exc
            raise

        ring_seconds = time.monotonic() - wall_started
        log.bind(ring_seconds=round(ring_seconds, 2)).info("call_broadcast.stream.connected")
        try:
            await start_remote_still_capture(
                pytgcalls=pytgcalls,
                account_id=str(account_id),
                chat_id=int(chat_id),
                job_id=job_id,
                trace_id=trace_id,
            )
        except Exception as exc:
            log.bind(error_type=type(exc).__name__).warning(
                "call_broadcast.remote_still.start_failed"
            )
        post_connect_delay = max(
            0.0,
            float(getattr(settings, "CALL_BROADCAST_POST_CONNECT_DELAY_SECONDS", 3)),
        )
        if post_connect_delay:
            log.bind(delay_seconds=post_connect_delay, mode="media_leadin").info(
                "call_broadcast.stream.preplay_delay"
            )
        log.info("call_broadcast.stream.playback_started")
        try:
            await asyncio.wait_for(asyncio.sleep(playback_seconds), timeout=playback_timeout)
        except asyncio.TimeoutError as exc:
            log.bind(playback_timeout=playback_timeout).warning(
                "call_broadcast.stream.timeout"
            )
            raise CallBroadcastStreamError(
                f"call playback exceeded {playback_timeout:.0f}s for chat_id={chat_id}"
            ) from exc
    finally:
        stream_wall_seconds = time.monotonic() - wall_started
        try:
            await asyncio.wait_for(
                stop_remote_still_capture(
                    account_id=str(account_id), chat_id=int(chat_id)
                ),
                timeout=_still_stop_timeout_seconds(),
            )
        except Exception as exc:
            log.bind(error_type=type(exc).__name__).warning(
                "call_broadcast.remote_still.stop_failed"
            )
        try:
            await asyncio.wait_for(
                _stop_stream(
                    pytgcalls,
                    chat_id,
                    account_id=account_id,
                    trace_id=trace_id,
                ),
                timeout=_hangup_timeout_seconds() + 2.0,
            )
        except Exception as exc:
            log.bind(error_type=type(exc).__name__).warning(
                "call_broadcast.hangup.timeout"
            )
        log.bind(stream_wall_seconds=round(stream_wall_seconds, 2)).info(
            "call_broadcast.stream.stop"
        )
    return CallPlaybackResult(
        playback_seconds=playback_seconds,
        probed_seconds=probed,
        stream_wall_seconds=stream_wall_seconds,
    )
