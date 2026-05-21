"""Hot-reloadable keyword rule engine for P3-06."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RULES_PATH = _REPO_ROOT / "config" / "intent_keyword_rules.json"


@dataclass(frozen=True)
class IntentKeywordRule:
    id: str
    intent: str
    priority: int = 0
    confidence: float = 0.75
    keywords: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()


@dataclass(frozen=True)
class IntentKeywordMatch:
    rule_id: str
    intent: str
    confidence: float
    priority: int
    matched_keywords: tuple[str, ...] = ()
    matched_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class IntentRuleSet:
    version: int
    confidence_floor: float
    rules: tuple[IntentKeywordRule, ...] = field(default_factory=tuple)


class IntentKeywordEngine:
    """Loads intent keyword rules and refreshes them when the JSON file changes."""

    def __init__(self, rules_path: Path = DEFAULT_RULES_PATH) -> None:
        self.rules_path = Path(rules_path)
        self._mtime_ns: int | None = None
        self._ruleset: IntentRuleSet | None = None

    @property
    def ruleset(self) -> IntentRuleSet:
        return self.load_if_changed()

    def load_if_changed(self, *, force: bool = False) -> IntentRuleSet:
        stat = self.rules_path.stat()
        if force or self._ruleset is None or stat.st_mtime_ns != self._mtime_ns:
            self._ruleset = _load_ruleset(self.rules_path)
            self._mtime_ns = stat.st_mtime_ns
            logger.bind(
                component="intent_keyword_engine",
                rules=len(self._ruleset.rules),
                version=self._ruleset.version,
            ).info("intent.keyword_rules.loaded")
        return self._ruleset

    def match(self, text: str) -> list[IntentKeywordMatch]:
        ruleset = self.load_if_changed()
        normalized = _normalize_text(text)
        if not normalized:
            return []

        matches: list[IntentKeywordMatch] = []
        for rule in ruleset.rules:
            if _excluded(normalized, rule.excludes):
                continue
            keyword_hits = tuple(k for k in rule.keywords if _keyword_in_text(normalized, k))
            pattern_hits = tuple(p for p in rule.patterns if re.search(p, normalized, re.I))
            if not keyword_hits and not pattern_hits:
                continue
            boost = min(0.08, 0.02 * max(0, len(keyword_hits) + len(pattern_hits) - 1))
            matches.append(
                IntentKeywordMatch(
                    rule_id=rule.id,
                    intent=rule.intent,
                    confidence=min(0.99, max(0.0, rule.confidence + boost)),
                    priority=rule.priority,
                    matched_keywords=keyword_hits,
                    matched_patterns=pattern_hits,
                )
            )
        return sorted(matches, key=lambda m: (-m.confidence, -m.priority, m.intent))


def _load_ruleset(path: Path) -> IntentRuleSet:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rules = tuple(_rule_from_dict(item) for item in raw.get("rules", []))
    return IntentRuleSet(
        version=int(raw.get("version", 1)),
        confidence_floor=float(raw.get("confidence_floor", 0.6)),
        rules=rules,
    )


def _rule_from_dict(data: dict[str, Any]) -> IntentKeywordRule:
    return IntentKeywordRule(
        id=str(data["id"]),
        intent=str(data["intent"]),
        priority=int(data.get("priority", 0)),
        confidence=float(data.get("confidence", 0.75)),
        keywords=tuple(str(k).lower() for k in data.get("keywords", [])),
        patterns=tuple(str(p) for p in data.get("patterns", [])),
        excludes=tuple(str(k).lower() for k in data.get("excludes", [])),
    )


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").lower().strip().split())


def _keyword_in_text(text: str, keyword: str) -> bool:
    needle = _normalize_text(keyword)
    if not needle:
        return False
    if any(ord(ch) > 127 for ch in needle):
        return needle in text
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", text, re.I) is not None


def _excluded(text: str, excludes: tuple[str, ...]) -> bool:
    return any(_keyword_in_text(text, keyword) for keyword in excludes)


intent_keyword_engine = IntentKeywordEngine()
