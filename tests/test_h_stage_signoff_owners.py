from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIGNOFFS = {
    "H-04": ("config/h04_persona_policy.json", "signed_by", "human_owner"),
    "H-05": ("config/h05_vip_h5_approval.json", "approved_by", "product_owner"),
    "H-07": ("config/h07_week9_cd_canary_approval.json", "approved_by", "release_owner"),
    "H-08": ("config/h08_week10_11_bas_approval.json", "approved_by", "release_owner"),
    "H-09": ("config/h09_operator_sop_training.json", "approved_by", "ops_owner"),
    "H-10": ("config/h10_go_no_go_signoff.json", "signed_by", "release_owner"),
    "H-11": ("config/h11_telegram_real_account_sop.json", "signed_by", "ops_owner"),
}


def test_h_stage_signoff_owners_are_finalized() -> None:
    for task_id, (rel, field, expected_owner) in SIGNOFFS.items():
        payload = json.loads((ROOT / rel).read_text(encoding="utf-8"))

        assert payload["task_id"] == task_id
        assert payload[field] == expected_owner
        assert "pending_final_review" not in payload[field]


def test_no_h_stage_config_keeps_pending_final_review_marker() -> None:
    for rel, _, _ in SIGNOFFS.values():
        text = (ROOT / rel).read_text(encoding="utf-8")

        assert "pending_final_review" not in text
