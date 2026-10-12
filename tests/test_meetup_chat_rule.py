"""见面规则：禁止拒绝，委婉延期；视频通话不算见面。"""
from __future__ import annotations

from services.product_i18n import (
    MEETUP_DEFER_COPY,
    is_in_person_meetup_request,
    meetup_defer_reply,
)
from services.reply_sanitize import (
    is_meetup_refusal,
    replace_meetup_refusal,
    sanitize_outbound_reply,
)


def test_meetup_intent_detected_by_tone_phrases():
    assert is_in_person_meetup_request("我们见面吧")
    assert is_in_person_meetup_request("想见你")
    assert is_in_person_meetup_request("wanna meet up")
    assert is_in_person_meetup_request("can we meet in person")
    assert is_in_person_meetup_request("let's hang out sometime")


def test_greeting_and_video_are_not_meetup():
    assert not is_in_person_meetup_request("nice to meet you")
    assert not is_in_person_meetup_request("很高兴认识你")
    assert not is_in_person_meetup_request("给我打视频")
    assert not is_in_person_meetup_request("视频见面吧")
    assert not is_in_person_meetup_request("facetime me")


def test_sanitize_rewrites_meetup_refusal_to_deferral():
    out = sanitize_outbound_reply(
        "Sorry, we can't meet in person. I only chat online.",
        user_text="wanna meet up",
    )
    assert "can't meet" not in out.casefold()
    assert "only chat" not in out.casefold()
    assert out == MEETUP_DEFER_COPY["en"]


def test_sanitize_rewrites_chinese_meetup_refusal():
    out = sanitize_outbound_reply(
        "我们不能见面，只能网上聊。",
        user_text="我们见面吧",
    )
    assert "不能见面" not in out
    assert "只能网上聊" not in out
    assert out == MEETUP_DEFER_COPY["zh"]


def test_generic_ai_refusal_on_meetup_uses_deferral_not_flirt():
    out = sanitize_outbound_reply(
        "I'm sorry, I can't help with that request.",
        user_text="can we meet",
    )
    assert out == MEETUP_DEFER_COPY["en"]
    assert "exactly what you want" not in out.casefold()


def test_warm_deferral_is_kept():
    text = "等我们再熟悉一些，成为朋友了我们会见面的。"
    out = sanitize_outbound_reply(text, user_text="想见你")
    assert "见面" in out
    assert "不能" not in out


def test_meetup_refusal_helper_and_replace():
    assert is_meetup_refusal("I can't meet you in person.")
    assert not is_meetup_refusal("We'll meet when we're closer.")
    rewritten = replace_meetup_refusal(
        "No podemos vernos.",
        user_text="podemos vernos",
    )
    assert rewritten == meetup_defer_reply("podemos vernos")
