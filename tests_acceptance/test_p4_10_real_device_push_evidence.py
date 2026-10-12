from __future__ import annotations

import json

from scripts.check_p4_10_real_device_push_evidence import (
    load_attempts,
    validate_real_device_push_evidence,
)


def test_p4_10_real_device_push_evidence_accepts_sanitized_success():
    ok, issues = validate_real_device_push_evidence(
        [
            {
                "provider": "fcm",
                "environment": "staging",
                "success": True,
                "message_id": "projects/demo/messages/123",
                "device_token_hash": "sha256:abcdef1234567890",
                "sent_at": "2026-05-21T12:00:00Z",
                "received_at": "2026-05-21T12:00:03Z",
            }
        ]
    )

    assert ok is True
    assert issues == []


def test_p4_10_real_device_push_evidence_rejects_raw_token():
    ok, issues = validate_real_device_push_evidence(
        [
            {
                "provider": "fcm",
                "environment": "staging",
                "success": True,
                "message_id": "msg-1",
                "device_token": "raw-token-must-not-be-stored",
                "device_token_hash": "sha256:abcdef1234567890",
                "received_at": "2026-05-21T12:00:03Z",
            }
        ]
    )

    assert ok is False
    assert any("must not contain raw token" in issue for issue in issues)


def test_p4_10_real_device_push_evidence_loader_accepts_attempts_object(tmp_path):
    path = tmp_path / "p4_10_push.json"
    path.write_text(json.dumps({"attempts": [{"provider": "apns"}]}), encoding="utf-8")

    assert load_attempts(path) == [{"provider": "apns"}]
