from services.product_i18n import (
    inbound_call_redirect_reply,
    is_inbound_call_help_request,
    is_outbound_call_request,
    strip_outbound_call_promises,
)
from services.video_request_handoff import is_live_video_call_request


def test_outbound_call_request_spanish():
    assert is_outbound_call_request("Llámame bb")
    assert is_outbound_call_request("Llama aca en telegram")
    assert is_outbound_call_request("Can you call me?")


def test_inbound_call_help_not_outbound():
    assert is_inbound_call_help_request("Donde te llamo bb")
    assert not is_outbound_call_request("Donde te llamo bb")


def test_inbound_call_redirect_copy_spanish():
    reply = inbound_call_redirect_reply("Llámame bb", language="es")
    assert "videollamada" in reply.casefold()


def test_video_chat_is_live_call_not_outbound_promise():
    assert is_live_video_call_request("video chat")
    reply = inbound_call_redirect_reply("video chat", language="pt")
    assert "perfil" in reply.casefold()
    assert "preparando" not in reply.casefold()
    assert "câmera" not in reply.casefold()


def test_strip_outbound_call_promises():
    cleaned = strip_outbound_call_promises(
        "Te llamaré ahora mismo, mi amor. Prepárate.",
        user_text="Llámame bb",
    )
    assert "llamar" not in cleaned.casefold()
    assert cleaned
