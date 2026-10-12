from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.intents import router
from services.intent_classifier import IntentClassifier, classify_intent
from services.intent_keyword_engine import IntentKeywordEngine


def test_p3_06_keyword_rules_hot_reload(tmp_path: Path):
    rules_path = tmp_path / "intent_keyword_rules.json"
    rules_path.write_text(
        json.dumps(
            {
                "version": 1,
                "rules": [
                    {
                        "id": "smalltalk.greeting.tmp",
                        "intent": "smalltalk.greeting",
                        "confidence": 0.8,
                        "keywords": ["hello"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    engine = IntentKeywordEngine(rules_path)

    assert engine.match("hello there")[0].intent == "smalltalk.greeting"
    assert engine.match("refund please") == []

    time.sleep(0.02)
    rules_path.write_text(
        json.dumps(
            {
                "version": 2,
                "rules": [
                    {
                        "id": "support.refund.tmp",
                        "intent": "support.refund",
                        "confidence": 0.9,
                        "keywords": ["refund"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    matches = engine.match("refund please")
    assert matches[0].intent == "support.refund"
    assert engine.ruleset.version == 2


def test_p3_07_classifier_returns_intent_and_confidence():
    result = classify_intent("How much does VIP cost?", locale="en")

    assert result.primary_intent == "conversion.price_question"
    assert result.confidence >= 0.6
    assert result.fallback is None
    assert "matched_keywords" in result.evidence


def test_p3_07_dual_recall_uses_labeled_examples_when_keywords_are_partial():
    classifier = IntentClassifier()

    result = classifier.classify("My hobbies include music and games.", locale="en")

    assert result.primary_intent == "onboarding.interests"
    assert result.confidence >= 0.6
    assert "semantic_example_ids" in result.evidence


def test_p3_08_low_confidence_falls_back_to_safe_smalltalk_strategy():
    result = classify_intent("blue seven umbrella")

    assert result.primary_intent == "fallback.unknown"
    assert result.confidence < 0.6
    assert result.fallback == "low_confidence"
    assert result.reply_strategy
    assert "tell me a little more" in result.reply_strategy


def test_p3_09_regression_set_has_at_least_50_examples_and_95_percent_accuracy():
    path = Path(__file__).resolve().parents[1] / "config" / "intent_regression_set.json"
    examples = json.loads(path.read_text(encoding="utf-8"))
    classifier = IntentClassifier()

    total = len(examples)
    correct = 0
    failures = []
    for example in examples:
        result = classifier.classify(example["text"], locale=example.get("locale"))
        accepted = {example["expected_primary_intent"], *example.get("acceptable_secondary_intents", [])}
        if result.primary_intent in accepted:
            correct += 1
        else:
            failures.append((example["text_id"], example["expected_primary_intent"], result.primary_intent))

    accuracy = correct / total
    assert total >= 50
    assert accuracy >= 0.95, failures


def test_intent_classify_api_contract():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/intents")
    client = TestClient(app)

    response = client.post(
        "/api/v1/intents/classify",
        json={"text": "I paid already, payment done.", "locale": "en"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["primary_intent"] == "conversion.post_payment"
    assert body["confidence"] >= 0.6
    assert "risk_flags" in body
