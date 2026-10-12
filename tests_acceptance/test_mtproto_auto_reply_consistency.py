import pytest

from services.mtproto import auto_reply
from services.reply_consistency import ADULT_FLIRT_FALLBACK_REPLY


class _Log:
    def __init__(self):
        self.events = []

    def info(self, event):
        self.events.append(("info", event))

    def warning(self, event):
        self.events.append(("warning", event))

    def bind(self, **_kwargs):
        return self


@pytest.mark.asyncio
async def test_mtproto_auto_reply_repairs_adult_flirt_refusal(monkeypatch):
    async def _ctx(_db, _conversation_id):
        return {"character": {"reply_length": "medium", "emoji_frequency": "low"}}

    monkeypatch.setattr(auto_reply, "load_reply_consistency_context", _ctx)

    output = await auto_reply._apply_reply_consistency(
        object(),
        "conv-1",
        "I'm not the right person to discuss that with. Let's keep our chat appropriate.",
        _Log(),
    )

    assert output == ADULT_FLIRT_FALLBACK_REPLY
