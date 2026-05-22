from __future__ import annotations

from types import SimpleNamespace

import pytest

import services.llm as llm


class _Response:
    def __init__(self, status_code: int, content: str = "ok") -> None:
        self.status_code = status_code
        self.text = content
        self._content = content

    def json(self):
        return {
            "choices": [{"message": {"content": self._content}}],
            "usage": {"total_tokens": 8},
        }


class _FakeAsyncClient:
    responses = []
    calls = []

    def __init__(self, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": self.timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture(autouse=True)
def reset_fake_client(monkeypatch):
    _FakeAsyncClient.responses = []
    _FakeAsyncClient.calls = []
    monkeypatch.setattr(llm.httpx, "AsyncClient", _FakeAsyncClient)


def _settings(**overrides):
    base = {
        "LLM_PROVIDER": "novita",
        "NOVITA_API_KEY": "novita-key",
        "LLM_API_BASE_URL": "https://api.novita.ai/openai/v1",
        "LLM_PRIMARY_MODEL": "deepseek/deepseek-v3-0324",
        "OPENROUTER_API_KEY": "openrouter-key",
        "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
        "LLM_FALLBACK_MODEL": "openai/gpt-4o-mini",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_novita_primary_uses_novita_api_key(monkeypatch):
    monkeypatch.setattr(llm, "settings", _settings())
    _FakeAsyncClient.responses = [_Response(200, "novita reply")]

    result = await llm.chat([{"role": "user", "content": "hi"}], trace_id="t1")

    assert result.content == "novita reply"
    assert result.model_used == "novita:deepseek/deepseek-v3-0324"
    assert result.fallback_used is False
    assert _FakeAsyncClient.calls[0]["url"] == "https://api.novita.ai/openai/v1/chat/completions"
    assert _FakeAsyncClient.calls[0]["headers"]["Authorization"] == "Bearer novita-key"


@pytest.mark.asyncio
async def test_novita_5xx_falls_back_to_openrouter(monkeypatch):
    monkeypatch.setattr(llm, "settings", _settings())
    _FakeAsyncClient.responses = [_Response(500, "upstream down"), _Response(200, "openrouter reply")]

    result = await llm.chat([{"role": "user", "content": "hi"}], trace_id="t2")

    assert result.content == "openrouter reply"
    assert result.model_used == "openrouter:openai/gpt-4o-mini"
    assert result.fallback_used is True
    assert _FakeAsyncClient.calls[1]["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert _FakeAsyncClient.calls[1]["headers"]["Authorization"] == "Bearer openrouter-key"


@pytest.mark.asyncio
async def test_missing_keys_return_structured_error(monkeypatch):
    monkeypatch.setattr(
        llm,
        "settings",
        _settings(NOVITA_API_KEY="", OPENROUTER_API_KEY=""),
    )

    result = await llm.chat([{"role": "user", "content": "hi"}], trace_id="t3")

    assert result.content == llm.DEFAULT_FALLBACK_REPLY
    assert result.error is not None
    assert "NOVITA_API_KEY_MISSING" in result.error
