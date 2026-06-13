"""Telethon + PyTgCalls video call broadcast (opt-in via CALL_BROADCAST_ENABLED)."""

from services.call_broadcast.keywords import is_video_call_request

__all__ = [
    "is_video_call_request",
]