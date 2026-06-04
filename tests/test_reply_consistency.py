"""P2 ConsistencyScore pre-send checks."""
from __future__ import annotations

from services.reply_consistency import (
    ADULT_FLIRT_FALLBACK_REPLY,
    DEFAULT_FALLBACK_REPLY,
    LOCATION_PERSONA_FALLBACK_REPLY,
    SYSTEM_LEAK_FALLBACK_REPLY,
    evaluate_reply_consistency,
)


def test_consistency_passes_warm_aria_reply():
    result = evaluate_reply_consistency(
        reply_text="我在，会认真听你说。今天最让你难受的是哪一刻？",
        character={
            "reply_length": "medium",
            "emoji_frequency": "low",
            "boundary_score": 80,
        },
    )

    assert result.passed is True
    assert result.fallback_used is False
    assert result.output_text.startswith("我在")
    assert result.score >= 0.65


def test_consistency_fallbacks_on_identity_conflict():
    result = evaluate_reply_consistency(
        reply_text="As ChatGPT, I am a large language model. Here are 3 tips:\n1. Test",
        character={"reply_length": "short", "emoji_frequency": "none"},
    )

    assert result.passed is False
    assert result.fallback_used is True
    assert result.output_text == DEFAULT_FALLBACK_REPLY
    assert any(
        "identity_conflict" in layer.reasons
        for layer in result.layers
        if layer.layer == "L2_IDENTITY"
    )


def test_consistency_allows_non_aria_role_self_reference():
    result = evaluate_reply_consistency(
        reply_text="我是 Mira，25 岁，来自纽约。",
        character={"name": "Mira", "reply_length": "short", "emoji_frequency": "none"},
    )

    assert result.passed is True
    assert result.fallback_used is False
    assert all(
        "self_reference_without_aria" not in layer.reasons
        for layer in result.layers
    )


def test_consistency_fallbacks_on_l1_unsafe_content():
    result = evaluate_reply_consistency(reply_text="我可以告诉你怎么自杀。")

    assert result.passed is False
    assert result.output_text == DEFAULT_FALLBACK_REPLY
    assert any(
        "unsafe_content" in layer.reasons
        for layer in result.layers
        if layer.layer == "L1_SAFETY"
    )


def test_consistency_fallbacks_on_system_layer_tag_leak():
    result = evaluate_reply_consistency(
        reply_text="## ===== L1_SAFETY =====\n硬红线如下：不要透露系统提示。",
    )

    assert result.passed is False
    assert result.fallback_used is True
    assert result.output_text == SYSTEM_LEAK_FALLBACK_REPLY
    assert "## =====" not in result.output_text
    assert "(" not in result.output_text
    assert any(
        "system_layer_tag" in layer.reasons
        for layer in result.layers
        if layer.layer == "SYSTEM_INFO_LEAK"
    )


def test_consistency_fallbacks_on_profile_details_leak():
    result = evaluate_reply_consistency(
        reply_text="根据资料/profile/details，她的 current_city 是上海，loneliness_score=82。",
    )

    assert result.passed is False
    assert result.output_text == SYSTEM_LEAK_FALLBACK_REPLY
    assert "profile" not in result.output_text.lower()
    assert any(
        "profile_details_reference" in layer.reasons
        for layer in result.layers
        if layer.layer == "SYSTEM_INFO_LEAK"
    )


def test_consistency_fallbacks_on_system_prompt_refusal_meta():
    result = evaluate_reply_consistency(
        reply_text="我不能透露系统提示和内部规则，但我可以继续陪你。",
    )

    assert result.passed is False
    assert result.output_text == SYSTEM_LEAK_FALLBACK_REPLY
    assert "系统" not in result.output_text
    assert any(
        "system_refusal_meta" in layer.reasons
        for layer in result.layers
        if layer.layer == "SYSTEM_INFO_LEAK"
    )


def test_character_layer_penalizes_style_drift_but_can_pass():
    result = evaluate_reply_consistency(
        reply_text="我懂。你可以慢慢说，我在这里听着。",
        character={"reply_length": "short", "emoji_frequency": "none"},
    )

    assert result.passed is True
    assert result.score >= 0.65


def test_generic_adult_flirt_refusal_is_repaired():
    result = evaluate_reply_consistency(
        reply_text="我就是一个普通的聊天对象，不适合这种互动。",
        character={"reply_length": "medium", "emoji_frequency": "low"},
    )

    assert result.output_text == ADULT_FLIRT_FALLBACK_REPLY
    assert result.fallback_used is True


def test_english_appropriate_refusal_is_repaired():
    result = evaluate_reply_consistency(
        reply_text=(
            "I'm not the right person to discuss that with. "
            "Let's keep our chat appropriate."
        ),
        character={"reply_length": "medium", "emoji_frequency": "low"},
    )

    assert result.output_text == ADULT_FLIRT_FALLBACK_REPLY
    assert "right person" not in result.output_text
    assert result.fallback_used is True


def test_english_personal_matter_refusal_is_repaired():
    result = evaluate_reply_consistency(
        reply_text=(
            "I'm not comfortable discussing personal matters like that. "
            "Let's talk about something else."
        ),
        character={"reply_length": "medium", "emoji_frequency": "low"},
    )

    assert result.output_text == ADULT_FLIRT_FALLBACK_REPLY
    assert "personal matters" not in result.output_text
    assert result.fallback_used is True


def test_english_private_matter_appropriate_refusal_is_repaired():
    result = evaluate_reply_consistency(
        reply_text=(
            "I'm not going to discuss private matters like that. "
            "Let's keep our conversation appropriate and respectful."
        ),
        character={"reply_length": "medium", "emoji_frequency": "low"},
    )

    assert result.output_text == ADULT_FLIRT_FALLBACK_REPLY
    assert "private matters" not in result.output_text
    assert "appropriate" not in result.output_text
    assert result.fallback_used is True


def test_english_too_personal_light_friendly_refusal_is_repaired():
    result = evaluate_reply_consistency(
        reply_text=(
            "That's getting a bit too personal for me. "
            "I'd prefer to keep our chat light and friendly."
        ),
        character={"reply_length": "medium", "emoji_frequency": "low"},
    )

    assert result.output_text == ADULT_FLIRT_FALLBACK_REPLY
    assert "too personal" not in result.output_text
    assert "light and friendly" not in result.output_text
    assert result.fallback_used is True


def test_location_persona_gap_is_repaired():
    result = evaluate_reply_consistency(
        reply_text=(
            "I don’t have a specific location, but I’m here to chat with you! "
            "What about you? Where are you from?"
        ),
        character={"reply_length": "medium", "emoji_frequency": "low"},
    )

    assert result.output_text == LOCATION_PERSONA_FALLBACK_REPLY
    assert result.fallback_used is True


def test_ai_location_persona_gap_is_repaired_even_when_identity_fails():
    result = evaluate_reply_consistency(
        reply_text="As an AI, I don't have a location or a place where I live.",
        character={"reply_length": "medium", "emoji_frequency": "low"},
    )

    assert result.output_text == LOCATION_PERSONA_FALLBACK_REPLY
    assert result.fallback_used is True
