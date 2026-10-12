from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPROVAL_PATH = ROOT / "config" / "h05_vip_h5_approval.json"


def _load_approval() -> dict:
    return json.loads(APPROVAL_PATH.read_text(encoding="utf-8"))


def test_h05_approval_is_product_accepted() -> None:
    approval = _load_approval()

    assert approval["task_id"] == "H-05"
    assert approval["status"] == "approved"
    assert approval["approved_on"] == "2026-05-20"
    assert approval["approved_by"] == "product_owner"
    assert "pending_final_review" not in approval["approved_by"]


def test_vip_offer_matches_payment_api_contract() -> None:
    approval = _load_approval()
    offer = approval["vip_offer"]
    request = approval["payment_redirect"]["create_order_request"]

    assert offer["product_id"] == "vip"
    assert offer["amount_cents"] == 499
    assert offer["currency"] == "USD"
    assert request["method"] == "POST"
    assert request["path"] == "/api/v1/orders"
    assert request["body"] == {
        "user_id": "{current_user_id}",
        "product_id": "vip",
        "amount": 499,
        "currency": "USD",
    }


def test_modal_copy_has_required_states() -> None:
    approval = _load_approval()
    modal = approval["modal"]

    assert modal["title"]
    assert modal["subtitle"]
    assert len(modal["body"]) >= 3
    assert len(modal["benefits"]) >= 3
    assert modal["primary_cta"]
    assert modal["secondary_cta"]
    assert modal["trust_note"]
    assert modal["age_gate_note"]
    assert modal["blocked_minor_message"]
    assert modal["error_message"]


def test_redirect_urls_match_config_defaults() -> None:
    approval = _load_approval()
    redirect = approval["payment_redirect"]

    assert (
        redirect["success_url"]
        == "https://hugme2.com/payment/success?session_id={CHECKOUT_SESSION_ID}"
    )
    assert redirect["cancel_url"] == "https://hugme2.com/payment/cancel"
    assert redirect["client_action"].startswith("Open checkout_url")


def test_product_acceptance_covers_safety_and_failure_states() -> None:
    approval = _load_approval()
    acceptance = "\n".join(approval["product_acceptance"]).lower()

    assert "checkout_url" in acceptance
    assert "age-unverified" in acceptance
    assert "suspected-minor" in acceptance
    assert "payment failure" in acceptance
