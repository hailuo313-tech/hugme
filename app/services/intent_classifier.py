"""Intent classifier for P3-07/P3-08/P3-09."""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from services.intent_keyword_engine import IntentKeywordEngine, intent_keyword_engine

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGRESSION_PATH = _REPO_ROOT / "config" / "intent_regression_set.json"
LOW_CONFIDENCE_THRESHOLD = 0.6

INTENT_PRIORITY = {
    "safety": 100,
    "boundary": 90,
    "support": 80,
    "onboarding": 70,
    "emotional_support": 60,
    "relationship": 50,
    "conversion": 40,
    "content_request": 30,
    "smalltalk": 20,
    "fallback": 0,
}

RISK_INTENTS: dict[str, str] = {}

LOW_CONFIDENCE_REPLY = "I want to understand you clearly. Could you tell me a little more?"

STOPWORDS = {
    "a",
    "about",
    "already",
    "am",
    "an",
    "and",
    "are",
    "be",
    "can",
    "do",
    "does",
    "for",
    "from",
    "here",
    "how",
    "i",
    "it",
    "is",
    "me",
    "my",
    "now",
    "of",
    "or",
    "please",
    "should",
    "that",
    "the",
    "there",
    "to",
    "what",
    "when",
    "why",
    "with",
    "you",
}


@dataclass(frozen=True)
class IntentCandidate:
    intent: str
    confidence: float
    source: str
    evidence: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class IntentClassification:
    primary_intent: str
    secondary_intents: list[str]
    confidence: float
    risk_flags: list[str]
    evidence: dict[str, list[str]]
    fallback: str | None = None
    reply_strategy: str | None = None
    latency_ms: float = 0.0

    def model_dump(self) -> dict[str, Any]:
        return {
            "primary_intent": self.primary_intent,
            "secondary_intents": self.secondary_intents,
            "confidence": self.confidence,
            "risk_flags": self.risk_flags,
            "evidence": self.evidence,
            "fallback": self.fallback,
            "reply_strategy": self.reply_strategy,
            "latency_ms": self.latency_ms,
        }


class IntentClassifier:
    """Combines keyword recall and labeled-example semantic recall."""

    def __init__(
        self,
        *,
        keyword_engine: IntentKeywordEngine = intent_keyword_engine,
        regression_path: Path = DEFAULT_REGRESSION_PATH,
    ) -> None:
        self.keyword_engine = keyword_engine
        self.regression_path = Path(regression_path)
        self._examples_mtime_ns: int | None = None
        self._examples: list[dict[str, Any]] = []

    def classify(self, text: str, *, locale: str | None = None, trace_id: str | None = None) -> IntentClassification:
        started = time.perf_counter()
        keyword_candidates = self._keyword_recall(text)
        semantic_candidates = self._semantic_recall(text, locale=locale)
        candidates = _merge_candidates(keyword_candidates + semantic_candidates)
        if not candidates:
            return self._fallback(started, reason="low_confidence", trace_id=trace_id)

        top = _choose_primary(candidates)
        if top.confidence < LOW_CONFIDENCE_THRESHOLD:
            return self._fallback(
                started,
                reason="low_confidence",
                trace_id=trace_id,
                confidence=round(top.confidence, 3),
                evidence=top.evidence,
            )

        secondary = [
            c.intent
            for c in candidates
            if c.intent != top.intent and c.confidence >= LOW_CONFIDENCE_THRESHOLD
        ][:3]
        risk_flags = sorted(
            {flag for candidate in candidates for flag in [RISK_INTENTS.get(candidate.intent)] if flag}
        )
        evidence = _merge_evidence([c.evidence for c in candidates if c.intent == top.intent])
        result = IntentClassification(
            primary_intent=top.intent,
            secondary_intents=secondary,
            confidence=round(top.confidence, 3),
            risk_flags=risk_flags,
            evidence=evidence,
            fallback=None,
            reply_strategy=None,
            latency_ms=_elapsed_ms(started),
        )
        logger.bind(
            component="intent",
            trace_id=trace_id,
            primary_intent=result.primary_intent,
            confidence=result.confidence,
            risk_flags=result.risk_flags,
            result="classified",
        ).info("intent.classify.done")
        return result

    def _keyword_recall(self, text: str) -> list[IntentCandidate]:
        candidates: list[IntentCandidate] = []
        for match in self.keyword_engine.match(text):
            candidates.append(
                IntentCandidate(
                    intent=match.intent,
                    confidence=match.confidence,
                    source="keyword",
                    evidence={
                        "rule_ids": [match.rule_id],
                        "matched_keywords": list(match.matched_keywords),
                        "matched_patterns": list(match.matched_patterns),
                    },
                )
            )
        return candidates

    def _semantic_recall(self, text: str, *, locale: str | None = None) -> list[IntentCandidate]:
        tokens = _tokenize(text)
        if not tokens:
            return []
        examples = self._load_examples()
        scored: list[tuple[float, dict[str, Any]]] = []
        for example in examples:
            expected = str(example.get("expected_primary_intent", ""))
            if expected.startswith("fallback."):
                continue
            if locale and example.get("locale") not in {locale, "en", "zh"}:
                continue
            score = _token_similarity(tokens, _tokenize(str(example.get("text", ""))))
            if score >= 0.35:
                scored.append((score, example))
        scored.sort(key=lambda item: item[0], reverse=True)
        candidates: list[IntentCandidate] = []
        for score, example in scored[:5]:
            confidence = min(0.89, 0.45 + math.sqrt(score) * 0.5)
            if confidence < 0.5:
                continue
            candidates.append(
                IntentCandidate(
                    intent=str(example["expected_primary_intent"]),
                    confidence=confidence,
                    source="semantic_examples",
                    evidence={"semantic_example_ids": [str(example["text_id"])]},
                )
            )
        return candidates

    def _load_examples(self) -> list[dict[str, Any]]:
        stat = self.regression_path.stat()
        if stat.st_mtime_ns != self._examples_mtime_ns:
            self._examples = json.loads(self.regression_path.read_text(encoding="utf-8"))
            self._examples_mtime_ns = stat.st_mtime_ns
        return self._examples

    def _fallback(
        self,
        started: float,
        *,
        reason: str,
        trace_id: str | None,
        confidence: float = 0.0,
        evidence: dict[str, list[str]] | None = None,
    ) -> IntentClassification:
        result = IntentClassification(
            primary_intent="fallback.unknown",
            secondary_intents=[],
            confidence=confidence,
            risk_flags=[],
            evidence=evidence or {},
            fallback=reason,
            reply_strategy=LOW_CONFIDENCE_REPLY,
            latency_ms=_elapsed_ms(started),
        )
        logger.bind(
            component="intent",
            trace_id=trace_id,
            primary_intent=result.primary_intent,
            confidence=result.confidence,
            risk_flags=[],
            result="fallback",
        ).info("intent.classify.done")
        return result


def classify_intent(
    text: str,
    *,
    locale: str | None = None,
    trace_id: str | None = None,
) -> IntentClassification:
    return intent_classifier.classify(text, locale=locale, trace_id=trace_id)


def low_confidence_reply() -> str:
    return LOW_CONFIDENCE_REPLY


def _merge_candidates(candidates: list[IntentCandidate]) -> list[IntentCandidate]:
    merged: dict[str, IntentCandidate] = {}
    for candidate in candidates:
        current = merged.get(candidate.intent)
        if current is None:
            merged[candidate.intent] = candidate
            continue
        merged[candidate.intent] = IntentCandidate(
            intent=candidate.intent,
            confidence=max(current.confidence, candidate.confidence),
            source=f"{current.source}+{candidate.source}",
            evidence=_merge_evidence([current.evidence, candidate.evidence]),
        )
    return sorted(
        merged.values(),
        key=lambda c: (-c.confidence, -_domain_priority(c.intent), c.intent),
    )


def _choose_primary(candidates: list[IntentCandidate]) -> IntentCandidate:
    strongest = max(candidates, key=lambda c: c.confidence)
    contenders = [
        c for c in candidates if c.confidence >= max(LOW_CONFIDENCE_THRESHOLD, strongest.confidence - 0.08)
    ]
    return sorted(
        contenders,
        key=lambda c: (-_domain_priority(c.intent), -c.confidence, c.intent),
    )[0]


def _domain_priority(intent: str) -> int:
    return INTENT_PRIORITY.get(intent.split(".", 1)[0], 0)


def _merge_evidence(items: list[dict[str, list[str]]]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for item in items:
        for key, values in item.items():
            bucket = merged.setdefault(key, [])
            for value in values:
                if value and value not in bucket:
                    bucket.append(value)
    return merged


def _tokenize(text: str) -> set[str]:
    lowered = str(text or "").lower()
    ascii_tokens = {
        token.strip("'")
        for token in re.findall(r"[a-z0-9']+", lowered)
        if token.strip("'") and token.strip("'") not in STOPWORDS
    }
    cjk_tokens = {ch for ch in lowered if "\u4e00" <= ch <= "\u9fff"}
    return {token for token in ascii_tokens | cjk_tokens if len(token) >= 2 or token in cjk_tokens}


def _token_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    if overlap == 0:
        return 0.0
    return overlap / max(len(left), len(right))


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


intent_classifier = IntentClassifier()
