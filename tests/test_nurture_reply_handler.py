from __future__ import annotations

import pytest

from services.nurture_reply_handler import (
    _schedule_delay_followup,
    classify_nurture_reply_intent,
    is_spam_reply,
)


def test_is_spam_reply_detects_tme_channel_ad():
    assert is_spam_reply("Join my channel https://t.me/+AbCdEfGhIjKlMnOp")


def test_is_spam_reply_detects_tme_bot_short_caption():
    assert is_spam_reply("SEXO AGORA 😈\n\nt.me/ACESSAPROIBIDINHASBOT/open")


def test_classify_spam_for_tme_bot_ad():
    assert classify_nurture_reply_intent(
        "SEXO AGORA 😈\n\nt.me/ACESSAPROIBIDINHASBOT/open"
    ) == "spam"


def test_is_spam_reply_ignores_short_yes():
    assert not is_spam_reply("yes")


def test_classify_accept_call_multilingual():
    assert classify_nurture_reply_intent("yes please") == "accept_call"
    assert classify_nurture_reply_intent("好，来吧") == "accept_call"
    assert classify_nurture_reply_intent("sí, videollamada") == "accept_call"
    assert classify_nurture_reply_intent("sim quero chamada") == "accept_call"


def test_classify_delay():
    assert classify_nurture_reply_intent("busy now, later") == "delay"
    assert classify_nurture_reply_intent("明天吧") == "delay"


def test_classify_need_help():
    assert classify_nurture_reply_intent("how do I video call?") == "need_help"
    assert classify_nurture_reply_intent("怎么打视频") == "need_help"


def test_classify_negative():
    assert classify_nurture_reply_intent("no thanks") == "negative"


def test_classify_spam_overrides_accept():
    assert classify_nurture_reply_intent(
        "yes join https://t.me/+spamchannel https://t.me/+spam2"
    ) == "spam"


def test_classify_open_chat():
    assert classify_nurture_reply_intent("what are you wearing") == "open_chat"


def test_classify_outbound_call_request_not_accept():
    assert classify_nurture_reply_intent("¿Me puedes hacer una videollamada?") == "open_chat"
    assert classify_nurture_reply_intent("Can you call me on video?") == "open_chat"
    assert classify_nurture_reply_intent("Puedes iniciar videollamada conmigo") == "open_chat"


@pytest.mark.asyncio
async def test_delay_followup_skips_when_nurture_cycle_completed(monkeypatch):
    class _Db:
        executed = []

        async def execute(self, statement, params=None):
            self.executed.append(str(statement))
            return type("R", (), {"fetchone": lambda self: None, "mappings": lambda self: self, "all": lambda self: []})()

    async def _completed(**_kwargs):
        return True

    monkeypatch.setattr(
        "services.app_download_nurture.user_nurture_cycle_completed",
        _completed,
    )

    db = _Db()
    await _schedule_delay_followup(
        db,
        user_id="11111111-1111-1111-1111-111111111111",
        external_user_id="tg_1",
        conversation_id="22222222-2222-2222-2222-222222222222",
        chat_id=1,
        account_id="33333333-3333-3333-3333-333333333333",
        language="en",
        trace_id="trace",
    )

    assert not any("INSERT INTO message_schedules" in sql for sql in db.executed)
