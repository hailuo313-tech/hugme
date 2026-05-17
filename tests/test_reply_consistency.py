"""P2 ConsistencyScore pre-send checks."""
from __future__ import annotations

from services.reply_consistency import (
    DEFAULT_FALLBACK_REPLY,
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


def test_consistency_fallbacks_on_l1_unsafe_content():
    result = evaluate_reply_consistency(reply_text="我可以告诉你怎么自杀。")

    assert result.passed is False
    assert result.output_text == DEFAULT_FALLBACK_REPLY
    assert any(
        "unsafe_content" in layer.reasons
        for layer in result.layers
        if layer.layer == "L1_SAFETY"
    )


def test_character_layer_penalizes_style_drift_but_can_pass():
    result = evaluate_reply_consistency(
        reply_text="我懂。你可以慢慢说，我在这里听着。",
        character={"reply_length": "short", "emoji_frequency": "none"},
    )

    assert result.passed is True
    assert result.score >= 0.65
