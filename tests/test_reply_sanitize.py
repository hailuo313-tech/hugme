from services.reply_sanitize import (
    default_max_reply_chars,
    flirt_fallback_reply,
    is_generic_ai_refusal,
    nurture_boilerplate_conflicts_with_llm_reply,
    replace_generic_ai_refusal,
    sanitize_outbound_reply,
)


def test_is_generic_ai_refusal_detects_chinese_template():
    assert is_generic_ai_refusal("对不起，我无法满足这个请求。") is True


def test_is_generic_ai_refusal_detects_portuguese_link_refusal():
    text = "Estou aqui para conversar, mas não posso acessar links ou conteúdo externo."
    assert is_generic_ai_refusal(text) is True


def test_sanitize_replaces_chinese_refusal():
    out = sanitize_outbound_reply(
        "对不起，我无法满足这个请求。",
        user_text="SEXO AGORA",
    )
    assert "对不起" not in out
    assert out == flirt_fallback_reply("SEXO AGORA")


def test_sanitize_replaces_portuguese_link_refusal():
    out = sanitize_outbound_reply(
        "Estou aqui para conversar, mas não posso acessar links ou conteúdo externo.",
        user_text="SEXO AGORA",
    )
    assert "não posso acessar" not in out.casefold()
    assert "Você está me deixando" in out


def test_is_generic_ai_refusal_detects_external_link_refusal():
    text = (
        "I'm unable to access external links. "
        "What topic are you interested in discussing?"
    )
    assert is_generic_ai_refusal(text) is True


def test_sanitize_replaces_external_link_refusal():
    out = sanitize_outbound_reply(
        "I'm unable to access external links. What topic are you interested in discussing?",
        user_text="send me something spicy",
    )
    assert "unable to access external links" not in out.lower()
    assert out == flirt_fallback_reply("send me something spicy")


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


def test_sanitize_strips_profile_age_system_leak():
    out = sanitize_outbound_reply(
        "No tengo una edad definida en mi perfil. Tengo 28 años.",
        user_text="cuántos años tienes",
    )
    assert "perfil" not in out.casefold()
    assert "28" in out


def test_nurture_boilerplate_conflicts_when_llm_refuses_outbound_call():
    nurture = "Perfect — tap call on my profile now and I'll pick up right away."
    llm = "Antes respondí jugando, pero en realidad no puedo hacer llamadas."
    assert nurture_boilerplate_conflicts_with_llm_reply(nurture, llm) is True
    assert nurture_boilerplate_conflicts_with_llm_reply(nurture, "Claro, te mando algo.") is False
