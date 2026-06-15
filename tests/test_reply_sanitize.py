from services.reply_sanitize import (
    default_max_reply_chars,
    flirt_fallback_reply,
    is_generic_ai_refusal,
    replace_generic_ai_refusal,
    sanitize_outbound_reply,
)


def test_is_generic_ai_refusal_detects_english_template():
    text = (
        "I'm sorry, but I can't comply with this request. "
        "I'm an AI assistant designed to provide helpful and harmless responses."
    )
    assert is_generic_ai_refusal(text) is True


def test_is_generic_ai_refusal_detects_italian_template():
    text = (
        "Non posso aiutarti con richieste di natura sessuale o esplicita. "
        "Se vuoi, possiamo parlare d'altro."
    )
    assert is_generic_ai_refusal(text) is True


def test_is_generic_ai_refusal_allows_normal_flirt_reply():
    assert is_generic_ai_refusal("You make me want to pull you closer right now.") is False


def test_replace_generic_ai_refusal_uses_italian_fallback():
    replaced = replace_generic_ai_refusal(
        "I'm sorry, but I can't comply with this request.",
        user_text="Mi fai eccitare",
    )
    assert "Mi stai accendendo" in replaced
    assert "AI assistant" not in replaced


def test_sanitize_outbound_reply_replaces_refusal_before_send():
    out = sanitize_outbound_reply(
        "I'm an AI assistant designed to provide helpful and appropriate conversations.",
        user_text="make me crazy",
    )
    assert "AI assistant" not in out
    assert out == flirt_fallback_reply("make me crazy")


def test_sanitize_strips_stage_actions():
    out = sanitize_outbound_reply("*smiles softly* Hey there, good to see you.")
    assert "*" not in out
    assert "Hey there" in out


def test_sanitize_collapses_paragraph_breaks():
    out = sanitize_outbound_reply("Line one.\n\nLine two.")
    assert "\n" not in out
    assert out == "Line one. Line two."


def test_sanitize_enforces_max_chars():
    long_text = "A" * 200 + " Still talking too much here."
    out = sanitize_outbound_reply(long_text, max_chars=120)
    assert len(out) <= 120
    assert out.endswith(".") or len(out) <= 120


def test_default_max_reply_chars_reads_settings(monkeypatch):
    from core import config

    monkeypatch.setattr(config.settings, "OUTBOUND_REPLY_MAX_CHARS", 90)
    assert default_max_reply_chars() == 90
