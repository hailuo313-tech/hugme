"""Helpers for turning MTProto inbound messages into replyable text."""

from __future__ import annotations

import re
from typing import Any


EMOJI_INBOUND_FALLBACK_TEXT = "🙂"
_LETTER_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]")
_STICKER_MIME_TYPES = {
    "application/x-tgsticker",
    "image/webp",
    "image/gif",
    "video/webm",
}
_STICKER_FILE_SUFFIXES = (".tgs", ".webp", ".webm", ".gif")


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _iter_document_attributes(message: Any) -> list[Any]:
    document = getattr(message, "document", None)
    media = getattr(message, "media", None)
    media_document = getattr(media, "document", None)
    attrs: list[Any] = []
    for candidate in (document, media_document, message):
        value = getattr(candidate, "attributes", None)
        if value:
            attrs.extend(list(value))
    return attrs


def _emoji_from_message_metadata(message: Any) -> str:
    media = getattr(message, "media", None)
    emoticon = _clean_text(getattr(media, "emoticon", None))
    if emoticon:
        return emoticon

    for attr in _iter_document_attributes(message):
        for field in ("alt", "emoticon", "emoji"):
            value = _clean_text(getattr(attr, field, None))
            if value:
                return value

    return ""


def is_emoji_only_user_text(text_value: Any) -> bool:
    """True for sticker fallbacks and messages that are only emoji/punctuation."""
    value = _clean_text(text_value)
    if not value:
        return False
    if value in {EMOJI_INBOUND_FALLBACK_TEXT, "[emoji]", "[sticker]"}:
        return True
    if _LETTER_RE.search(value):
        return False
    return len(value) <= 12


def _file_name(message: Any) -> str:
    document = getattr(message, "document", None)
    media = getattr(message, "media", None)
    media_document = getattr(media, "document", None)
    for candidate in (message, document, media_document):
        for field in ("file_name", "filename", "name"):
            value = _clean_text(getattr(candidate, field, None)).lower()
            if value:
                return value
        file_obj = getattr(candidate, "file", None)
        value = _clean_text(getattr(file_obj, "name", None)).lower()
        if value:
            return value
    for attr in _iter_document_attributes(message):
        value = _clean_text(getattr(attr, "file_name", None)).lower()
        if value:
            return value
    return ""


def _looks_like_emoji_or_sticker_message(message: Any) -> bool:
    if message is None:
        return False
    if getattr(message, "sticker", None) or getattr(message, "gif", None):
        return True

    media = getattr(message, "media", None)
    media_name = type(media).__name__.lower() if media is not None else ""
    if any(token in media_name for token in ("dice", "sticker", "emoji", "gif")):
        return True
    if _clean_text(getattr(media, "emoticon", None)):
        return True

    document = getattr(message, "document", None) or getattr(media, "document", None)
    mime_type = _clean_text(
        getattr(document, "mime_type", None) or getattr(message, "mime_type", None)
    ).lower()
    if mime_type in _STICKER_MIME_TYPES:
        return True

    file_name = _file_name(message)
    if file_name.endswith(_STICKER_FILE_SUFFIXES):
        return True

    for attr in _iter_document_attributes(message):
        attr_name = type(attr).__name__.lower()
        if any(token in attr_name for token in ("sticker", "customemoji", "animated")):
            return True

    for entity in getattr(message, "entities", None) or []:
        if "customemoji" in type(entity).__name__.lower():
            return True

    return False


def inbound_media_skip_context(message: Any) -> dict[str, Any]:
    media = getattr(message, "media", None)
    document = getattr(message, "document", None) or getattr(media, "document", None)
    return {
        "media_type": type(media).__name__ if media is not None else "",
        "mime_type": _clean_text(
            getattr(document, "mime_type", None) or getattr(message, "mime_type", None)
        ),
        "file_name": _file_name(message),
        "has_sticker": bool(getattr(message, "sticker", None)),
        "has_gif": bool(getattr(message, "gif", None)),
        "has_photo": bool(getattr(message, "photo", None)),
        "has_document": bool(document is not None),
        "looks_like_emoji": _looks_like_emoji_or_sticker_message(message),
    }


def inbound_text_for_reply(message: Any) -> str:
    """Return text that should enter the normal reply flow.

    Telegram sticker/custom-emoji/dice messages can arrive without raw text. They
    are still user contact, especially as a first message, so turn them into a
    small text surrogate instead of dropping the turn as empty.
    """

    for field in ("raw_text", "text", "message"):
        value = _clean_text(getattr(message, field, None))
        if value:
            return value

    emoji = _emoji_from_message_metadata(message)
    if emoji:
        return emoji

    if _looks_like_emoji_or_sticker_message(message):
        return EMOJI_INBOUND_FALLBACK_TEXT

    # Telethon does not expose every sticker/GIF/media variant consistently
    # across API layers. In a private chat, any actual media attachment is a
    # valid user turn and must not be dropped merely because it has no caption.
    media = getattr(message, "media", None)
    if media is not None or any(
        getattr(message, field, None)
        for field in ("document", "photo", "video", "voice", "audio")
    ):
        return EMOJI_INBOUND_FALLBACK_TEXT

    return ""
