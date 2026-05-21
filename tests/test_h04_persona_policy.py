from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "h04_persona_policy.json"


def _load_policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def test_h04_policy_is_signed() -> None:
    policy = _load_policy()

    assert policy["task_id"] == "H-04"
    assert policy["status"] == "signed"
    assert policy["signed_on"] == "2026-05-20"
    assert policy["signed_by"] == "human_owner"
    assert "pending_final_review" not in policy["signed_by"]


def test_required_personas_are_approved() -> None:
    policy = _load_policy()
    personas = {item["slug"]: item for item in policy["approved_personas"]}

    assert set(personas) >= {
        "aria_warm_friend",
        "mira_playful_muse",
        "sol_calm_guide",
    }
    for persona in personas.values():
        assert persona["tone_family"]
        assert persona["personality"]["allowed_traits"]
        assert persona["personality"]["disallowed_traits"]
        assert persona["reply_style"]["must_answer_first"] is True
        assert persona["reply_style"]["stage_directions_allowed"] is False
        assert persona["persona_safety_notes"]


def test_required_forbidden_categories_are_present() -> None:
    policy = _load_policy()
    categories = {
        item["category"]: item["terms"]
        for item in policy["forbidden_term_categories"]
    }

    assert set(categories) >= {
        "system_disclosure",
        "performative_style",
        "unsafe_minors",
        "self_harm_enabling",
        "illegal_harm",
        "conversion_forbidden_contexts",
    }
    for terms in categories.values():
        assert terms


def test_guardrails_keep_safety_above_persona() -> None:
    policy = _load_policy()
    guardrails = "\n".join(policy["global_guardrails"]).lower()

    assert "override persona tone" in guardrails
    assert "never reveal" in guardrails
    assert "stage directions" in guardrails
    assert "match the user's language" in guardrails
    assert "do not upsell" in guardrails
