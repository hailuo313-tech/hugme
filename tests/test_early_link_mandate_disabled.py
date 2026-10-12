"""Early-link mandate is disabled: first replies must not force an App URL."""
from __future__ import annotations

import asyncio

from services.app_download_conversion import _needs_early_link_mandate
from services.mtproto.auto_reply import _ensure_first_reply_app_link


def test_early_link_mandate_never_triggers():
    assert asyncio.run(_needs_early_link_mandate(
        None,
        user_id="x",
        conversation_id="y",
        user_message_limit=1,
    )) is False


def test_first_reply_no_longer_appends_app_link():
    text = "Hi there."
    out = asyncio.run(_ensure_first_reply_app_link(
        None,
        conversation_id="y",
        user_id="x",
        reply_text=text,
        user_text="hello",
        trigger_message_id=None,
        trace_id="t",
    ))
    assert out == text
