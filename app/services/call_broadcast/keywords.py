"""Detect inbound requests for a live/private video call."""

from __future__ import annotations

import re

# Exact-match test codes: send only this text to trigger an immediate video call.
TEST_IMMEDIATE_VIDEO_CALL_CODES: tuple[str, ...] = (
    "8866",
)

# Exact single-word messages that mean a live call in this product context.
STANDALONE_VIDEO_CALL_TOKENS: tuple[str, ...] = (
    "video",
    "vid",
    "cam",
    "cam2",
    "vc",
)

_CJK_KEYWORDS: tuple[str, ...] = (
    "视频通话",
    "视频电话",
    "打视频",
    "开视频",
    "视讯",
    "裸聊",
)

VIDEO_CALL_KEYWORDS: tuple[str, ...] = (
    "video call",
    "videocall",
    "facetime",
    "face time",
    "cam2cam",
    "c2c",
    "live show",
    "private call",
    "call me",
    "video chat",
    * _CJK_KEYWORDS,
)

_ASCII_COMPILED = tuple(
    re.compile(rf"(?<!\w){re.escape(token)}(?!\w)", re.IGNORECASE)
    for token in VIDEO_CALL_KEYWORDS
    if token.isascii()
)


def _normalized(text: str | None) -> str:
    return " ".join(str(text or "").casefold().split())


def is_immediate_video_call_code(text: str | None) -> bool:
    """Return True when the message is an exact test code (e.g. 8866)."""
    return _normalized(text) in TEST_IMMEDIATE_VIDEO_CALL_CODES


def is_video_call_request(text: str | None) -> bool:
    """Return True when the user asks for a real-time call, not just a file."""
    value = _normalized(text)
    if not value:
        return False
    if value in STANDALONE_VIDEO_CALL_TOKENS:
        return True
    if is_immediate_video_call_code(value):
        return True
    if any(token in value for token in _CJK_KEYWORDS):
        return True
    return any(pattern.search(value) for pattern in _ASCII_COMPILED)


def matched_video_call_keyword(text: str | None) -> str | None:
    value = _normalized(text)
    if not value:
        return None
    if value in STANDALONE_VIDEO_CALL_TOKENS:
        return value
    if value in TEST_IMMEDIATE_VIDEO_CALL_CODES:
        return value
    for token in _CJK_KEYWORDS:
        if token in value:
            return token
    for token, pattern in zip(
        [t for t in VIDEO_CALL_KEYWORDS if t.isascii()],
        _ASCII_COMPILED,
    ):
        if pattern.search(value):
            return token
    return None
