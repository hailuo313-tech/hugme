from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
H5_CHAT_PAGE = ROOT / "admin" / "app" / "h5" / "chat" / "page.tsx"
APPROVAL_PATH = ROOT / "config" / "h05_vip_h5_approval.json"
BUSINESS_FLOW_PATH = ROOT / "docs" / "product" / "business-flow.html"


def _approval() -> dict:
    return json.loads(APPROVAL_PATH.read_text(encoding="utf-8"))


def _h5_source() -> str:
    return H5_CHAT_PAGE.read_text(encoding="utf-8")


def test_p4_09_vip_cta_uses_approved_order_contract() -> None:
    approval = _approval()
    request = approval["payment_redirect"]["create_order_request"]
    offer = approval["vip_offer"]
    src = _h5_source()

    assert f'const VIP_ORDER_PATH = "{request["path"]}"' in src
    assert f'const VIP_PRODUCT_ID = "{offer["product_id"]}"' in src
    assert f"const VIP_AMOUNT_CENTS = {offer['amount_cents']}" in src
    assert f'const VIP_CURRENCY = "{offer["currency"]}"' in src
    assert 'method: "POST"' in src
    assert "body: JSON.stringify" in src


def test_p4_09_vip_cta_redirects_to_checkout_url_only() -> None:
    src = _h5_source()

    assert "checkout_url" in src
    assert "window.location.assign(order.checkout_url)" in src
    assert "checkout.stripe.com" not in src
    assert "STRIPE_SUCCESS_URL" not in src
    assert "STRIPE_CANCEL_URL" not in src


def test_p4_09_modal_contains_approved_copy_and_error_states() -> None:
    approval = _approval()
    modal = approval["modal"]
    src = _h5_source()

    for key in ("title", "subtitle", "primary_cta", "secondary_cta"):
        assert modal[key] in src

    assert modal["trust_note"] in src
    assert modal["age_gate_note"] in src
    assert modal["blocked_minor_message"] in src
    assert modal["error_message"] in src


def test_p4_09_business_flow_marked_done() -> None:
    src = BUSINESS_FLOW_PATH.read_text(encoding="utf-8")
    task_line = re.search(r'\{ id:"P4-09".*?\}', src)

    assert task_line is not None
    assert "baseline:true" in task_line.group(0)
