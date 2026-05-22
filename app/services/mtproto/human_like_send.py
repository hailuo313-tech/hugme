"""Human-like MTProto outbound sending helpers (P1-11)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Any, Awaitable, Callable, Optional

from loguru import logger


SleepFn = Callable[[float], Awaitable[None]]
ClockFn = Callable[[], float]


@dataclass(frozen=True)
class HumanLikeSendPolicy:
    """Timing policy shared by MTProto real-user outbound delivery."""

    short_text_seconds: float = 4.0
    medium_text_seconds: float = 7.0
    long_text_seconds: float = 11.0
    very_long_text_seconds: float = 18.0
    minimum_typing_seconds: float = 2.0
    minimum_inter_message_seconds: float = 8.0


DEFAULT_HUMAN_LIKE_SEND_POLICY = HumanLikeSendPolicy()


def human_typing_delay_seconds(
    text: str,
    *,
    policy: HumanLikeSendPolicy = DEFAULT_HUMAN_LIKE_SEND_POLICY,
) -> float:
    """Return the simulated typing duration for a message."""
    size = len(text or "")
    if size <= 10:
        delay = policy.short_text_seconds
    elif size <= 30:
        delay = policy.medium_text_seconds
    elif size <= 50:
        delay = policy.long_text_seconds
    else:
        delay = policy.very_long_text_seconds
    return max(policy.minimum_typing_seconds, delay)


async def send_typing(
    client: Any,
    peer: Any,
    *,
    duration_seconds: Optional[float] = None,
    policy: HumanLikeSendPolicy = DEFAULT_HUMAN_LIKE_SEND_POLICY,
    sleep: SleepFn = asyncio.sleep,
) -> None:
    """Ask Telethon to show a typing action for the target peer."""
    action = getattr(client, "action", None)
    if action is None:
        raise TypeError("MTProto client does not expose Telethon-style action()")

    maybe_context = action(peer, "typing")
    try:
        async with maybe_context:
            duration = policy.minimum_typing_seconds if duration_seconds is None else duration_seconds
            if duration > 0:
                await sleep(duration)
            return None
    except Exception as exc:
        logger.bind(peer=str(peer), error_type=type(exc).__name__).warning("mtproto.typing_failed")
        return None


async def wait_for_inter_message_gap(
    *,
    last_sent_at: Optional[float],
    policy: HumanLikeSendPolicy = DEFAULT_HUMAN_LIKE_SEND_POLICY,
    sleep: SleepFn = asyncio.sleep,
    now: ClockFn = monotonic,
) -> None:
    """Enforce the H-11 same-account minimum gap when caller has prior send time."""
    if last_sent_at is None:
        return
    remaining = policy.minimum_inter_message_seconds - (now() - last_sent_at)
    if remaining > 0:
        await sleep(remaining)


async def send_human_like_message(
    client: Any,
    peer: Any,
    text: str,
    *,
    policy: HumanLikeSendPolicy = DEFAULT_HUMAN_LIKE_SEND_POLICY,
    last_sent_at: Optional[float] = None,
    sleep: SleepFn = asyncio.sleep,
    now: ClockFn = monotonic,
    **send_kwargs: Any,
) -> Any:
    """Show typing, wait like a human, then send a Telethon message."""
    await wait_for_inter_message_gap(
        last_sent_at=last_sent_at,
        policy=policy,
        sleep=sleep,
        now=now,
    )
    typing_delay = human_typing_delay_seconds(text, policy=policy)
    action = getattr(client, "action", None)
    if action is None:
        raise TypeError("MTProto client does not expose Telethon-style action()")

    try:
        async with action(peer, "typing"):
            await sleep(typing_delay)
    except Exception as exc:
        logger.bind(peer=str(peer), error_type=type(exc).__name__).warning("mtproto.typing_failed")

    return await client.send_message(peer, text, **send_kwargs)
