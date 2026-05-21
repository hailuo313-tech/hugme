"""P5-03 regression gate for level and intent fixtures."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.intent_classifier import IntentClassifier
from services.level_engine import UserLevelInput, calc_user_level

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEVEL_REGRESSION_PATH = _REPO_ROOT / "config" / "level_regression_set.json"
DEFAULT_INTENT_REGRESSION_PATH = _REPO_ROOT / "config" / "intent_regression_set.json"


@dataclass(frozen=True)
class RegressionFailure:
    suite: str
    case_id: str
    expected: dict[str, Any]
    actual: dict[str, Any]


@dataclass(frozen=True)
class RegressionSuiteResult:
    suite: str
    total: int
    passed: int
    failures: list[RegressionFailure]

    @property
    def failed(self) -> int:
        return len(self.failures)

    @property
    def accuracy(self) -> float:
        return self.passed / self.total if self.total else 1.0

    def model_dump(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "accuracy": round(self.accuracy, 4),
            "failures": [
                {
                    "suite": failure.suite,
                    "case_id": failure.case_id,
                    "expected": failure.expected,
                    "actual": failure.actual,
                }
                for failure in self.failures
            ],
        }


@dataclass(frozen=True)
class RegressionGateResult:
    suites: list[RegressionSuiteResult]

    @property
    def total(self) -> int:
        return sum(suite.total for suite in self.suites)

    @property
    def failed(self) -> int:
        return sum(suite.failed for suite in self.suites)

    @property
    def passed(self) -> int:
        return self.total - self.failed

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def model_dump(self) -> dict[str, Any]:
        return {
            "task_id": "P5-03",
            "status": "passed" if self.ok else "failed",
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "suites": [suite.model_dump() for suite in self.suites],
        }


def run_regression_gate(
    *,
    level_path: Path = DEFAULT_LEVEL_REGRESSION_PATH,
    intent_path: Path = DEFAULT_INTENT_REGRESSION_PATH,
    classifier: IntentClassifier | None = None,
) -> RegressionGateResult:
    return RegressionGateResult(
        suites=[
            run_level_regression(level_path=level_path),
            run_intent_regression(intent_path=intent_path, classifier=classifier),
        ]
    )


def run_level_regression(*, level_path: Path = DEFAULT_LEVEL_REGRESSION_PATH) -> RegressionSuiteResult:
    cases = json.loads(level_path.read_text(encoding="utf-8"))
    failures: list[RegressionFailure] = []

    for case in cases:
        data = dict(case["input"])
        result = calc_user_level(UserLevelInput(**data))
        actual = {
            "level": result.level,
            "chat_route": result.chat_route,
            "reason": result.reason,
            "country_tier": result.country_tier,
        }
        expected = {
            "level": case["expected_level"],
            "chat_route": case["expected_chat_route"],
            "reason": case["expected_reason"],
            "country_tier": case["expected_country_tier"],
        }
        if actual != expected:
            failures.append(
                RegressionFailure(
                    suite="level",
                    case_id=str(case["case_id"]),
                    expected=expected,
                    actual=actual,
                )
            )

    return RegressionSuiteResult(
        suite="level",
        total=len(cases),
        passed=len(cases) - len(failures),
        failures=failures,
    )


def run_intent_regression(
    *,
    intent_path: Path = DEFAULT_INTENT_REGRESSION_PATH,
    classifier: IntentClassifier | None = None,
) -> RegressionSuiteResult:
    cases = json.loads(intent_path.read_text(encoding="utf-8"))
    intent_classifier = classifier or IntentClassifier()
    failures: list[RegressionFailure] = []

    for case in cases:
        result = intent_classifier.classify(case["text"], locale=case.get("locale"))
        accepted = {
            str(case["expected_primary_intent"]),
            *[str(intent) for intent in case.get("acceptable_secondary_intents", [])],
        }
        if result.primary_intent not in accepted:
            failures.append(
                RegressionFailure(
                    suite="intent",
                    case_id=str(case["text_id"]),
                    expected={
                        "primary_intent": case["expected_primary_intent"],
                        "accepted": sorted(accepted),
                    },
                    actual={
                        "primary_intent": result.primary_intent,
                        "confidence": result.confidence,
                    },
                )
            )

    return RegressionSuiteResult(
        suite="intent",
        total=len(cases),
        passed=len(cases) - len(failures),
        failures=failures,
    )
