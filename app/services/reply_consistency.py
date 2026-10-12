"""Outbound reply consistency guard removed — pass-through (pending rewrite)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_FALLBACK_REPLY = ""
ADULT_FLIRT_FALLBACK_REPLY = ""
LOCATION_PERSONA_FALLBACK_REPLY = ""
SYSTEM_LEAK_FALLBACK_REPLY = ""
LOCATION_PERSONA_FALLBACK_REPLY_ZH = ""


@dataclass(frozen=True)
class ConsistencyLayerResult:
    layer: str
    passed: bool
    score: float
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReplyConsistencyResult:
    score: float
    passed: bool
    output_text: str
    original_text: str
    fallback_used: bool
    layers: list[ConsistencyLayerResult]

    def as_log_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "passed": self.passed,
            "fallback_used": self.fallback_used,
            "layers": [],
            "skipped": True,
            "reason": "reply_consistency_removed",
        }


def evaluate_reply_consistency(
    *,
    reply_text: str,
    character: dict[str, Any] | None = None,
    threshold: float = 0.65,
    fallback_reply: str = DEFAULT_FALLBACK_REPLY,
    system_leak_fallback_reply: str = SYSTEM_LEAK_FALLBACK_REPLY,
) -> ReplyConsistencyResult:
    text = (reply_text or "").strip()
    return ReplyConsistencyResult(
        score=1.0,
        passed=True,
        output_text=text,
        original_text=text,
        fallback_used=False,
        layers=[],
    )


async def load_reply_consistency_context(db: Any, conversation_id: str) -> dict[str, Any]:
    return {"character": None}
