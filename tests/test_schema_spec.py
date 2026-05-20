from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema_spec.json"


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_schema_spec_json_is_parseable_and_named_for_p1_13():
    schema = _load_schema()

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == "ERIS Standard Inbound Message"
    assert schema["properties"]["schema_version"]["const"] == "p1-13.v1"


def test_schema_spec_requires_standard_inbound_envelope():
    schema = _load_schema()

    assert set(schema["required"]) == {
        "schema_version",
        "platform",
        "channel",
        "account",
        "sender",
        "message",
        "received_at",
    }
    assert schema["additionalProperties"] is False


def test_schema_spec_contains_account_id_and_sender_phone_contract():
    schema = _load_schema()

    account = schema["properties"]["account"]
    sender = schema["properties"]["sender"]

    assert "account_id" in account["required"]
    assert account["properties"]["account_id"]["minLength"] == 1
    assert "sender_phone" in sender["properties"]
    assert sender["properties"]["sender_phone"]["pattern"] == "^\\+[1-9][0-9]{5,14}$"


def test_schema_spec_covers_mtproto_and_h5_app_adapter_platforms():
    schema = _load_schema()

    assert set(schema["properties"]["platform"]["enum"]) == {
        "telegram_bot",
        "telegram_real_user",
        "h5",
        "app",
        "test",
    }
    assert set(schema["properties"]["message"]["properties"]["message_type"]["enum"]) >= {
        "text",
        "photo",
        "voice",
    }


def test_schema_spec_example_matches_core_required_fields():
    schema = _load_schema()
    example = schema["examples"][0]

    for field in schema["required"]:
        assert field in example

    assert example["platform"] == "telegram_real_user"
    assert example["channel"] == "telegram"
    assert example["account"]["account_id"]
    assert example["sender"]["external_user_id"].startswith("tg_")
    assert example["sender"]["sender_phone"].startswith("+")
    assert example["message"]["message_type"] == "text"
    assert example["message"]["content"]
    assert example["idempotency"]["key"]
