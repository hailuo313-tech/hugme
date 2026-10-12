"""Outbound sanitize: drop model/system refusals before they reach the user."""
from __future__ import annotations

from services.reply_sanitize import (
    is_generic_ai_refusal,
    merge_first_reply_with_app_link,
    sanitize_outbound_reply,
)

MANDATE = (
    "Download this app to video chat with me one-on-one; open here to view explicit photos and videos:\n"
    "tap https://hugme2.com/r/abc (code: c5a8we)"
)


def test_chinese_media_refusal_is_detected():
    text = "抱歉，我无法处理该请求。 Thanks."
    assert is_generic_ai_refusal(text)


def test_chinese_media_refusal_is_rewritten_not_sent():
    out = sanitize_outbound_reply(
        "抱歉，我无法处理该请求。 Thanks.",
        user_text="[media]",
    )
    assert "无法处理" not in out
    assert "抱歉" not in out
    assert "Thanks." not in out
    assert out


def test_english_media_capability_refusal_is_rewritten():
    out = sanitize_outbound_reply(
        "I don't have the capability to view or interpret media content.",
        user_text="[media]",
    )
    assert "capability" not in out.casefold()
    assert "interpret media" not in out.casefold()


def test_first_reply_link_replaces_system_refusal_instead_of_appending():
    merged = merge_first_reply_with_app_link(
        "抱歉，我无法处理该请求。 Thanks.",
        MANDATE,
    )
    assert merged == MANDATE
    assert "无法处理" not in merged


def test_first_reply_link_keeps_in_character_reply():
    merged = merge_first_reply_with_app_link("My skin is warm against the sheets.", MANDATE)
    assert merged.startswith("My skin is warm against the sheets.")
    assert "Download this app" in merged
