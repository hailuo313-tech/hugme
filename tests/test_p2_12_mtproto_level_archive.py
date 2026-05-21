from __future__ import annotations

import json

from scripts.check_p2_12_mtproto_level_archive import (
    load_events,
    validate_mtproto_level_archive,
)


def test_p2_12_mtproto_archive_accepts_valid_real_user_level_event():
    ok, issues = validate_mtproto_level_archive(
        [
            {
                "platform": "telegram_real_user",
                "external_user_id": "tg_hash_001",
                "account_id": "acc_001",
                "message_type": "text",
                "environment": "staging",
                "metadata": {
                    "user_level": "B",
                    "chat_route": "ai_assisted",
                    "level_reason": "t1_default_b",
                    "country_tier": "T1",
                },
            }
        ]
    )

    assert ok is True
    assert issues == []


def test_p2_12_mtproto_archive_rejects_missing_or_wrong_route():
    ok, issues = validate_mtproto_level_archive(
        [
            {
                "platform": "telegram_real_user",
                "external_user_id": "tg_hash_001",
                "account_id": "acc_001",
                "message_type": "text",
                "metadata": {
                    "user_level": "S",
                    "chat_route": "ai_auto",
                    "level_reason": "operator_assigned_s",
                    "country_tier": "T1",
                },
            }
        ]
    )

    assert ok is False
    assert any("chat_route does not match level" in issue for issue in issues)


def test_p2_12_mtproto_archive_loader_accepts_events_object(tmp_path):
    path = tmp_path / "p2_12_archive.json"
    path.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "platform": "telegram_real_user",
                        "metadata": {"user_level": "C", "chat_route": "ai_auto"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    events = load_events(path)

    assert events[0]["platform"] == "telegram_real_user"
