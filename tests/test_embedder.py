"""D3-4 单元测试：app/services/embedder.py

覆盖：
- happy path：OpenAI 风格响应 → vectors 同序、长度匹配
- 缺 OPENAI_API_KEY → 直接返回 error
- 4xx：不重试，立刻报错
- 5xx：重试一次后失败
- 超时：网络异常被捕获
- 空输入：返回空 result，不调网络
- 乱序 index：按 index 排序回原序
- _vector_literal：格式正确
"""

from __future__ import annotations

import importlib
from typing import Any, Optional

import pytest


# ─────────────────────────────────────────────────────────────
# fixtures
# ─────────────────────────────────────────────────────────────


@pytest.fixture
def emb_mod():
    import services.embedder as mod  # type: ignore

    importlib.reload(mod)
    return mod


class _FakeResp:
    def __init__(self, status_code: int = 200, payload: Optional[dict] = None, text_body: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text_body or "body"

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeClient:
    """模拟 httpx.AsyncClient async-with 行为。"""

    def __init__(self, responses: list[Any]):
        # 每次 post() 弹出一个；元素可以是 _FakeResp 或异常实例
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if not self.responses:
            raise AssertionError("no more fake responses")
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _patch_client(monkeypatch, emb_mod, responses: list[Any]) -> _FakeClient:
    client = _FakeClient(responses)

    def _factory(*args, **kwargs):
        return client

    monkeypatch.setattr(emb_mod.httpx, "AsyncClient", _factory)
    return client


def _patch_settings(monkeypatch, emb_mod, *, key="sk-xxx", model="text-embedding-3-small"):
    monkeypatch.setattr(emb_mod.settings, "OPENAI_API_KEY", key, raising=False)
    monkeypatch.setattr(emb_mod.settings, "EMBEDDING_MODEL", model, raising=False)


def _ok_payload(vectors: list[list[float]]) -> dict:
    return {
        "data": [{"index": i, "embedding": v, "object": "embedding"} for i, v in enumerate(vectors)],
        "model": "text-embedding-3-small",
        "usage": {"prompt_tokens": 5, "total_tokens": 5},
    }


# ─────────────────────────────────────────────────────────────
# happy path
# ─────────────────────────────────────────────────────────────


class TestEmbedHappy:
    @pytest.mark.asyncio
    async def test_returns_vectors_in_order(self, emb_mod, monkeypatch):
        _patch_settings(monkeypatch, emb_mod)
        vecs = [[0.1] * 1536, [0.2] * 1536]
        _patch_client(monkeypatch, emb_mod, [_FakeResp(200, _ok_payload(vecs))])

        res = await emb_mod.embed(["hello", "world"], trace_id="t1")
        assert res.error is None
        assert len(res.vectors) == 2
        assert res.vectors[0][0] == pytest.approx(0.1)
        assert res.vectors[1][0] == pytest.approx(0.2)
        assert res.model_used == "text-embedding-3-small"
        assert res.usage.get("total_tokens") == 5

    @pytest.mark.asyncio
    async def test_reorders_by_index(self, emb_mod, monkeypatch):
        _patch_settings(monkeypatch, emb_mod)
        payload = {
            "data": [
                {"index": 1, "embedding": [0.2, 0.2]},
                {"index": 0, "embedding": [0.1, 0.1]},
            ],
            "usage": {},
        }
        _patch_client(monkeypatch, emb_mod, [_FakeResp(200, payload)])

        res = await emb_mod.embed(["a", "b"], trace_id="t2")
        assert res.error is None
        assert res.vectors[0] == [0.1, 0.1]
        assert res.vectors[1] == [0.2, 0.2]

    @pytest.mark.asyncio
    async def test_empty_input_short_circuit(self, emb_mod, monkeypatch):
        _patch_settings(monkeypatch, emb_mod)
        client = _patch_client(monkeypatch, emb_mod, [])
        res = await emb_mod.embed([], trace_id="t3")
        assert res.error is None
        assert res.vectors == []
        assert client.calls == []  # 没发 HTTP


# ─────────────────────────────────────────────────────────────
# 错误路径
# ─────────────────────────────────────────────────────────────


class TestEmbedErrors:
    @pytest.mark.asyncio
    async def test_missing_api_key(self, emb_mod, monkeypatch):
        _patch_settings(monkeypatch, emb_mod, key=None)
        res = await emb_mod.embed(["hi"], trace_id="t")
        assert res.error == "OPENAI_API_KEY_MISSING"
        assert res.vectors == []

    @pytest.mark.asyncio
    async def test_4xx_no_retry(self, emb_mod, monkeypatch):
        _patch_settings(monkeypatch, emb_mod)
        # 准备两个 4xx；如果重试了，就会消费第二个
        responses = [_FakeResp(401, {}, "no auth"), _FakeResp(401, {}, "no auth")]
        client = _patch_client(monkeypatch, emb_mod, responses)
        res = await emb_mod.embed(["hi"], trace_id="t")
        assert res.error and res.error.startswith("4xx:401")
        assert len(client.calls) == 1  # 没重试

    @pytest.mark.asyncio
    async def test_5xx_retried_then_failed(self, emb_mod, monkeypatch):
        _patch_settings(monkeypatch, emb_mod)
        responses = [_FakeResp(503, {}, "down"), _FakeResp(503, {}, "down")]
        client = _patch_client(monkeypatch, emb_mod, responses)
        res = await emb_mod.embed(["hi"], trace_id="t")
        assert res.error and res.error.startswith("5xx:503")
        assert len(client.calls) == 2  # 重试一次

    @pytest.mark.asyncio
    async def test_5xx_then_recover(self, emb_mod, monkeypatch):
        _patch_settings(monkeypatch, emb_mod)
        responses = [
            _FakeResp(502, {}, "boom"),
            _FakeResp(200, _ok_payload([[0.5, 0.5]])),
        ]
        client = _patch_client(monkeypatch, emb_mod, responses)
        res = await emb_mod.embed(["hi"], trace_id="t")
        assert res.error is None
        assert res.vectors == [[0.5, 0.5]]
        assert len(client.calls) == 2

    @pytest.mark.asyncio
    async def test_timeout_caught(self, emb_mod, monkeypatch):
        import httpx

        _patch_settings(monkeypatch, emb_mod)
        responses = [httpx.TimeoutException("slow"), httpx.TimeoutException("slow")]
        _patch_client(monkeypatch, emb_mod, responses)
        res = await emb_mod.embed(["hi"], trace_id="t")
        assert res.error and res.error.startswith("timeout:")

    @pytest.mark.asyncio
    async def test_vector_count_mismatch_retried(self, emb_mod, monkeypatch):
        _patch_settings(monkeypatch, emb_mod)
        bad = {"data": [{"index": 0, "embedding": [0.1]}], "usage": {}}
        responses = [_FakeResp(200, bad), _FakeResp(200, bad)]
        _patch_client(monkeypatch, emb_mod, responses)
        res = await emb_mod.embed(["a", "b"], trace_id="t")
        assert res.error == "vector_count_mismatch"


# ─────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────


class TestVectorLiteral:
    def test_format(self, emb_mod):
        s = emb_mod._vector_literal([1.0, -2.5, 0.0])
        assert s.startswith("[") and s.endswith("]")
        parts = s[1:-1].split(",")
        assert len(parts) == 3
        # 不应包含科学计数或空格
        assert " " not in s
        assert "e" not in s.lower()

    def test_long_vector_no_separator_issue(self, emb_mod):
        vec = [0.123456789] * 1536
        s = emb_mod._vector_literal(vec)
        # 1536 个数字 + 1535 个逗号 + 2 个括号
        assert s.count(",") == 1535
