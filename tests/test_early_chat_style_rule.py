"""前 10 条聊天规则：直接口语作答，不要疑问语 / 书面陈述语 / 感叹语 / 夸张描绘。"""
from __future__ import annotations

from services.prompt_builder import EARLY_REPLY_NO_QUESTION_LIMIT, PromptInput, build_prompt
from services.reply_sanitize import apply_early_spoken_style, sanitize_outbound_reply


def test_prompt_requires_direct_spoken_answer():
    system = build_prompt(PromptInput(user_text="你从哪来？")).system_content
    assert "直接回答问题本身" in system
    assert "口语化" in system
    assert "日常聊天化" in system
    assert f"前 {EARLY_REPLY_NO_QUESTION_LIMIT} 条" in system or "前10条" in system


def test_sanitize_drops_early_questions_and_exclamations():
    out = sanitize_outbound_reply(
        "I'm 24! What about you?",
        user_text="how old are you",
        early_spoken_style=True,
    )
    assert "?" not in out
    assert "!" not in out
    assert "What about you" not in out
    assert "24" in out


def test_sanitize_keeps_questions_after_early_window():
    out = sanitize_outbound_reply(
        "I'm 24. What about you?",
        user_text="how old are you",
        early_spoken_style=False,
    )
    assert "What about you" in out


def test_sanitize_chinese_question_and_exclamation():
    out = sanitize_outbound_reply(
        "我在洛杉矶！你呢？",
        user_text="你在哪",
        early_spoken_style=True,
    )
    assert "？" not in out
    assert "！" not in out
    assert "你呢" not in out
    assert "洛杉矶" in out


def test_apply_early_spoken_style_converts_lone_question():
    out = apply_early_spoken_style("Where are you from?")
    assert "?" not in out
    assert "Where are you from" in out
