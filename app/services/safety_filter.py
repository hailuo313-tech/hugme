"""Unified safety filter for P3-12 (redlines + inbound gate removed)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SafetyFilterResult:
    blocked: bool
    block_reason: str | None
    redline_id: str | None = None
    category: str | None = None
    layers: dict[str, Any] = field(default_factory=dict)


class SafetyFilter:
    async def evaluate(self, text: str, *, trace_id: str) -> SafetyFilterResult:
        return SafetyFilterResult(
            blocked=False,
            block_reason=None,
            layers={"redline": {"skipped": True}, "content_safety": {"skipped": True}},
        )


async def evaluate_safety_filter(text: str, *, trace_id: str) -> SafetyFilterResult:
    return await safety_filter.evaluate(text, trace_id=trace_id)


safety_filter = SafetyFilter()
