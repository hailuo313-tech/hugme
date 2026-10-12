from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "P3_INTENT_TAXONOMY.md"


def test_intent_taxonomy_doc_exists_and_names_downstream_tasks():
    text = DOC_PATH.read_text(encoding="utf-8")

    assert "P3-05" in text
    assert "P3-06" in text
    assert "P3-07" in text
    assert "P3-09" in text
    assert "P3-20" in text


def test_intent_taxonomy_doc_defines_required_domains():
    text = DOC_PATH.read_text(encoding="utf-8")

    for domain in (
        "smalltalk",
        "emotional_support",
        "relationship",
        "onboarding",
        "conversion",
        "support",
        "content_request",
        "boundary",
        "safety",
        "fallback",
    ):
        assert f"`{domain}`" in text


def test_intent_taxonomy_doc_includes_core_classifier_contract():
    text = DOC_PATH.read_text(encoding="utf-8")

    for field in (
        "primary_intent",
        "secondary_intents",
        "confidence",
        "risk_flags",
        "evidence",
        "fallback",
    ):
        assert field in text


def test_intent_taxonomy_doc_documents_guardrails_and_privacy():
    text = DOC_PATH.read_text(encoding="utf-8")

    assert "Do not log raw user content" in text
    assert "minor" in text.lower()
    assert "opt_out_marketing" in text
    assert "crisis protocol" in text
