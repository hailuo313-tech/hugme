"""Reply consistency removed — pass-through stub."""
from __future__ import annotations

from services.reply_consistency import evaluate_reply_consistency


def test_reply_consistency_passes_through_unchanged():
    reply = "I can't share that kind of content with you."
    result = evaluate_reply_consistency(
        reply_text=reply,
        character={"reply_length": "short", "emoji_frequency": "none"},
    )

    assert result.passed is True
    assert result.fallback_used is False
    assert result.output_text == reply
