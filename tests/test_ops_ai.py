from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.admin import require_operator
from api.ops_ai import router
from core.database import get_db

CONVERSATION_ID = "00000000-0000-0000-0000-000000000601"
HANDOFF_ID = "00000000-0000-0000-0000-000000000602"
OPERATOR_ID = "00000000-0000-0000-0000-000000000603"


def _row(data: dict[str, Any]) -> MagicMock:
    row = MagicMock()
    row._mapping = data
    return row


def _result(*, rows: list[Any] | None = None, one: Any | None = None) -> MagicMock:
    res = MagicMock()
    res.fetchall.return_value = rows or []
    res.fetchone.return_value = one
    return res


def _conversation_row() -> MagicMock:
    return _row(
        {
            "conversation_id": CONVERSATION_ID,
            "state": "WAITING_OPERATOR",
            "channel": "telegram",
            "last_message_at": "2026-05-16T00:02:00",
            "created_at": "2026-05-16T00:00:00",
            "user_id": "00000000-0000-0000-0000-000000000604",
            "nickname": "Mina",
            "external_id": "tg-1",
            "risk_level": "normal",
            "language": "zh-CN",
            "loneliness_score": 72.0,
            "vip_level": 1,
            "relationship_stage": "S2",
            "chat_style": "gentle",
            "interests": ["music"],
            "forbidden_topics": [],
            "character_id": "00000000-0000-0000-0000-000000000605",
            "character_name": "Aria",
        }
    )


def _message_row(sender_type: str, content: str) -> MagicMock:
    return _row(
        {
            "id": "00000000-0000-0000-0000-000000000606",
            "sender_type": sender_type,
            "content": content,
            "content_type": "text",
            "is_operator_message": sender_type == "operator",
            "model_name": None,
            "created_at": "2026-05-16T00:01:00",
        }
    )


def _app(db: Any, *, with_auth: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/ops-ai")

    async def _fake_db() -> AsyncGenerator[Any, None]:
        yield db

    app.dependency_overrides[get_db] = _fake_db

    if with_auth:

        async def _fake_operator() -> dict:
            return {"sub": OPERATOR_ID, "type": "operator", "role": "admin"}

        app.dependency_overrides[require_operator] = _fake_operator

    return app


def _llm_payload(reply_count: int = 3) -> str:
    replies = [
        {"rank": 1, "text": "我在的，刚刚让你等了。", "reason": "先安抚等待焦虑。"},
        {"rank": 2, "text": "我理解你会担心，我们一步步看。", "reason": "降低紧张感。"},
        {"rank": 3, "text": "谢谢你告诉我，我会认真处理。", "reason": "表达重视。"},
    ][:reply_count]
    return json.dumps(
        {
            "summary": {
                "user_state": "用户有点焦虑，想得到确认。",
                "key_facts": ["用户刚表达了等待回复的不安。"],
                "risk_flags": [],
                "recommended_strategy": "先共情，再给出明确下一步。",
            },
            "suggested_replies": replies,
        },
        ensure_ascii=False,
    )


def _db_with_conversation(*, rows: list[Any] | None = None) -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _result(one=_conversation_row()),
            _result(rows=rows if rows is not None else [_message_row("user", "你还在吗？")]),
        ]
    )
    return db


def _patch_llm(monkeypatch, *, content: str | None = None, error: str | None = None):
    mock_chat = AsyncMock(
        return_value=SimpleNamespace(
            content=content if content is not None else _llm_payload(),
            model_used="test-model",
            error=error,
        )
    )
    monkeypatch.setattr("api.ops_ai.llm_chat", mock_chat)
    return mock_chat


def test_ops_ai_assist_requires_operator_token():
    db = MagicMock()
    client = TestClient(_app(db, with_auth=False))

    r = client.post(f"/api/v1/ops-ai/conversations/{CONVERSATION_ID}/assist", json={})

    assert r.status_code == 401


def test_ops_ai_translate_requires_operator_token():
    db = MagicMock()
    client = TestClient(_app(db, with_auth=False))

    r = client.post(
        "/api/v1/ops-ai/translate",
        json={"items": [{"id": "m1", "text": "Hello"}]},
    )

    assert r.status_code == 401


def test_ops_ai_translate_returns_chinese_display_text(monkeypatch):
    db = MagicMock()
    mock_chat = _patch_llm(
        monkeypatch,
        content=json.dumps(
            {
                "translations": [
                    {"id": "m1", "text": "你好，我来自纽约。"},
                    {"id": "m2", "text": "你是谁？"},
                ]
            },
            ensure_ascii=False,
        ),
    )
    client = TestClient(_app(db))

    r = client.post(
        "/api/v1/ops-ai/translate",
        json={
            "target_language": "zh-CN",
            "preserve_terms": ["Mina93"],
            "items": [
                {"id": "m1", "sender_type": "assistant", "text": "Hi, I am from New York."},
                {"id": "m2", "sender_type": "user", "text": "你是谁？"},
            ],
        },
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["translations"] == [
        {"id": "m1", "text": "你好，我来自纽约。"},
        {"id": "m2", "text": "你是谁？"},
    ]
    llm_messages = mock_chat.await_args.kwargs["messages"]
    assert "简体中文" in llm_messages[0]["content"]
    assert "Mina93" in llm_messages[1]["content"]


def test_ops_ai_translate_falls_back_to_original_missing_ids(monkeypatch):
    db = MagicMock()
    _patch_llm(
        monkeypatch,
        content=json.dumps({"translations": [{"id": "other", "text": "忽略"}]}, ensure_ascii=False),
    )
    client = TestClient(_app(db))

    r = client.post(
        "/api/v1/ops-ai/translate",
        json={"items": [{"id": "m1", "text": "Original text"}]},
    )

    assert r.status_code == 200, r.text
    assert r.json()["translations"] == [{"id": "m1", "text": "Original text"}]


def test_ops_ai_assist_conversation_not_found():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(one=None))
    client = TestClient(_app(db))

    r = client.post(f"/api/v1/ops-ai/conversations/{CONVERSATION_ID}/assist", json={})

    assert r.status_code == 404
    assert r.json()["detail"] == "conversation not found"


def test_ops_ai_assist_returns_summary_and_three_replies(monkeypatch):
    db = _db_with_conversation()
    mock_chat = _patch_llm(monkeypatch)
    client = TestClient(_app(db))

    r = client.post(
        f"/api/v1/ops-ai/conversations/{CONVERSATION_ID}/assist",
        json={
            "handoff_task_id": HANDOFF_ID,
            "language": "zh-CN",
            "tone": "warm",
            "max_context_messages": 12,
        },
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["conversation_id"] == CONVERSATION_ID
    assert body["handoff_task_id"] == HANDOFF_ID
    assert body["summary"]["user_state"]
    assert len(body["suggested_replies"]) == 3
    assert [item["rank"] for item in body["suggested_replies"]] == [1, 2, 3]
    assert db.execute.await_args_list[1].args[1]["limit"] == 12
    llm_messages = mock_chat.await_args.kwargs["messages"]
    assert llm_messages[0]["role"] == "system"
    assert "exactly 3" in llm_messages[0]["content"]


def test_ops_ai_assist_passthrough_handoff_task_id(monkeypatch):
    db = _db_with_conversation()
    _patch_llm(monkeypatch)
    client = TestClient(_app(db))

    r = client.post(
        f"/api/v1/ops-ai/conversations/{CONVERSATION_ID}/assist",
        json={"handoff_task_id": HANDOFF_ID},
    )

    assert r.status_code == 200
    assert r.json()["handoff_task_id"] == HANDOFF_ID


def test_ops_ai_assist_llm_error_returns_502(monkeypatch):
    db = _db_with_conversation()
    _patch_llm(monkeypatch, error="API_KEY_MISSING")
    client = TestClient(_app(db))

    r = client.post(f"/api/v1/ops-ai/conversations/{CONVERSATION_ID}/assist", json={})

    assert r.status_code == 502
    assert r.json()["detail"] == "AI assist generation failed"


def test_ops_ai_assist_llm_exception_returns_502(monkeypatch):
    db = _db_with_conversation()
    monkeypatch.setattr("api.ops_ai.llm_chat", AsyncMock(side_effect=RuntimeError("boom")))
    client = TestClient(_app(db))

    r = client.post(f"/api/v1/ops-ai/conversations/{CONVERSATION_ID}/assist", json={})

    assert r.status_code == 502
    assert r.json()["detail"] == "AI assist generation failed"


def test_ops_ai_assist_bad_json_returns_502(monkeypatch):
    db = _db_with_conversation()
    _patch_llm(monkeypatch, content="not-json")
    client = TestClient(_app(db))

    r = client.post(f"/api/v1/ops-ai/conversations/{CONVERSATION_ID}/assist", json={})

    assert r.status_code == 502
    assert "invalid JSON" in r.json()["detail"]


def test_ops_ai_assist_caps_context_messages_at_80():
    db = MagicMock()
    client = TestClient(_app(db))

    r = client.post(
        f"/api/v1/ops-ai/conversations/{CONVERSATION_ID}/assist",
        json={"max_context_messages": 81},
    )

    assert r.status_code == 422


def test_ops_ai_assist_rejects_zero_context_messages():
    db = MagicMock()
    client = TestClient(_app(db))

    r = client.post(
        f"/api/v1/ops-ai/conversations/{CONVERSATION_ID}/assist",
        json={"max_context_messages": 0},
    )

    assert r.status_code == 422


def test_ops_ai_assist_rejects_invalid_tone():
    db = MagicMock()
    client = TestClient(_app(db))

    r = client.post(
        f"/api/v1/ops-ai/conversations/{CONVERSATION_ID}/assist",
        json={"tone": "angry"},
    )

    assert r.status_code == 422


def test_ops_ai_assist_no_messages_still_returns_result(monkeypatch):
    db = _db_with_conversation(rows=[])
    _patch_llm(monkeypatch)
    client = TestClient(_app(db))

    r = client.post(f"/api/v1/ops-ai/conversations/{CONVERSATION_ID}/assist", json={})

    assert r.status_code == 200
    assert len(r.json()["suggested_replies"]) == 3


def test_ops_ai_assist_pads_missing_replies(monkeypatch):
    db = _db_with_conversation()
    _patch_llm(monkeypatch, content=_llm_payload(reply_count=1))
    client = TestClient(_app(db))

    r = client.post(f"/api/v1/ops-ai/conversations/{CONVERSATION_ID}/assist", json={})

    assert r.status_code == 200
    replies = r.json()["suggested_replies"]
    assert len(replies) == 3
    assert replies[0]["text"] == "我在的，刚刚让你等了。"
    assert replies[1]["text"]
    assert replies[2]["text"]
