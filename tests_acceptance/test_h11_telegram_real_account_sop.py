from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "h11_telegram_real_account_sop.json"


def _load_policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def test_h11_policy_is_signed() -> None:
    policy = _load_policy()

    assert policy["task_id"] == "H-11"
    assert policy["status"] == "signed"
    assert policy["signed_on"] == "2026-05-20"
    assert policy["signed_by"] == "ops_owner"
    assert "pending_final_review" not in policy["signed_by"]


def test_production_session_plaintext_is_forbidden() -> None:
    policy = _load_policy()
    account_policy = policy["account_policy"]

    assert account_policy["session_storage"] == "production_db_ciphertext_only"
    assert account_policy["production_plaintext_session_strings_allowed"] is False
    assert account_policy["one_client_per_account_id"] is True
    assert account_policy["stable_user_account_routing_required"] is True
    assert account_policy["redis_prefix_isolation_required"] is True


def test_frequency_limits_are_conservative_and_present() -> None:
    policy = _load_policy()
    per_account = policy["rate_limits"]["per_account"]
    global_pool = policy["rate_limits"]["global_pool"]

    assert per_account["new_dialogs_per_hour_max"] <= 5
    assert per_account["new_dialogs_per_day_max"] <= 30
    assert per_account["outbound_messages_per_minute_max"] <= 3
    assert per_account["outbound_messages_per_hour_max"] <= 60
    assert per_account["outbound_messages_per_day_max"] <= 300
    assert per_account["same_user_messages_per_minute_max"] <= 2
    assert per_account["minimum_inter_message_delay_seconds"] >= 8
    assert global_pool["pool_outbound_messages_per_minute_max"] <= 10


def test_batching_disables_cold_outreach_and_marketing_blasts() -> None:
    policy = _load_policy()
    batching = policy["rate_limits"]["batching"]

    assert batching["batch_size_max"] <= 20
    assert batching["batch_cooldown_minutes"] >= 20
    assert batching["parallel_accounts_per_batch_max"] <= 3
    assert batching["marketing_blast_enabled"] is False
    assert batching["cold_outreach_enabled"] is False


def test_tos_guardrails_cover_abuse_and_evasion() -> None:
    policy = _load_policy()
    guardrails = "\n".join(policy["tos_guardrails"]).lower()

    assert "spam" in guardrails
    assert "unsolicited bulk" in guardrails
    assert "evade telegram limits" in guardrails
    assert "flood" in guardrails
    assert "opt-out" in guardrails


def test_pause_conditions_and_incident_actions_exist() -> None:
    policy = _load_policy()
    pause = "\n".join(policy["pause_conditions"]).lower()
    actions = "\n".join(policy["operator_runbook"]["incident_actions"]).lower()

    assert "floodwait" in pause
    assert "banned" in pause
    assert "failures exceed 5%" in pause
    assert "disable the affected account_id" in actions
    assert "preserve logs after redaction" in actions
