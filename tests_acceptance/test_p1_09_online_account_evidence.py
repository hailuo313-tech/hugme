from __future__ import annotations

import json

from scripts.check_p1_09_online_account import has_online_real_account, load_rows


def test_p1_09_online_account_evidence_requires_real_online_account():
    assert has_online_real_account(
        [
            {"is_bot": True, "is_active": True, "status": "connected"},
            {"is_bot": False, "is_active": True, "status": "disconnected"},
            {"is_bot": False, "is_active": False, "status": "connected"},
        ]
    ) is False

    assert has_online_real_account(
        [
            {
                "account_id": "acc-real-1",
                "is_bot": False,
                "is_active": True,
                "status": "connected",
                "environment": "staging",
            }
        ]
    ) is True


def test_p1_09_online_account_evidence_loader_accepts_accounts_object(tmp_path):
    evidence = tmp_path / "p1_09_online_accounts.json"
    evidence.write_text(
        json.dumps({"accounts": [{"is_bot": False, "status": "online"}]}),
        encoding="utf-8",
    )

    assert load_rows(evidence) == [{"is_bot": False, "status": "online"}]
