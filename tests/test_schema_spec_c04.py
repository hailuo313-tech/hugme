"""C-04: schema_spec.json and adapter envelope contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.inbound.envelope import (
    StandardInboundEnvelope,
    from_legacy_http_inbound,
    load_schema_spec,
    schema_spec_path,
    validate_against_schema_spec,
)


def test_schema_spec_file_exists_and_parses():
    path = schema_spec_path()
    assert path.is_file()
    schema = load_schema_spec()
    assert schema["title"] == "ERIS Standard Inbound Envelope"
    assert "telegram_real_user" in schema["properties"]["platform"]["enum"]


def test_mtproto_envelope_validates():
    env = StandardInboundEnvelope(
        platform="telegram_real_user",
        account_id="acc-1",
        sender_phone="+15551234567",
        external_user_id="tg_99",
        message_type="text",
        content="hello",
        trace_id="abcd1234efgh5678",
        metadata={
            "telegram_message_id": "42",
            "telegram_chat_id": "chat_123",
            "idempotency_key": "key_456",
            "raw_update_id": "update_789"
        },
        received_at="2024-01-01T00:00:00Z",
    )
    issues = validate_against_schema_spec(env.model_dump(mode="json"))
    assert issues == []


def test_mtproto_missing_account_id_fails_schema():
    raw = {
        "platform": "telegram_real_user",
        "external_user_id": "tg_1",
        "message_type": "text",
        "content": "x",
        "trace_id": "trace0001trace",
        "metadata": {"telegram_message_id": "1"},
    }
    issues = validate_against_schema_spec(raw)
    assert issues


def test_legacy_http_mapping():
    env = from_legacy_http_inbound(
        channel="telegram",
        external_user_id="tg_1",
        message_type="text",
        content="hi",
        trace_id="trace0001trace",
        account_id="acc_1",
        sender_phone="+15551234567",
        metadata={
            "telegram_message_id": "9",  # 使用正确的字段名
            "telegram_chat_id": "chat_123",
            "idempotency_key": "key_456",
            "raw_update_id": "update_789"
        },
        received_at="2024-01-01T00:00:00Z",
    )
    assert env.platform == "telegram"
    issues = validate_against_schema_spec(env.model_dump(mode="json"))
    assert issues == []


def test_schema_spec_required_keys_documented():
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "docs" / "schema_spec.json").read_text(encoding="utf-8"))
    for key in ("platform", "account_id", "sender_phone", "external_user_id"):
        assert key in schema["properties"]
