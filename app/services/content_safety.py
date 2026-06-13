"""Inbound content safety gate removed — always pass through.

Legacy ``messages.safety_result`` callers may still invoke
``evaluate_inbound_content_safety``; it never blocks.
"""
from __future__ import annotations

from typing import Any


def _keyword_hit(text: str) -> tuple[bool, str | None]:
    return False, None


def _moderation_should_block(
    categories: dict[str, Any],
    category_scores: dict[str, Any],
    flagged: bool,
) -> tuple[bool, str | None]:
    return False, None


async def evaluate_inbound_content_safety(
    text: str,
    *,
    trace_id: str,
) -> dict[str, Any]:
    return {
        "blocked": False,
        "block_reason": None,
        "keyword": {"skipped": True, "reason": "content_safety_removed"},
        "moderation": {"skipped": True, "reason": "content_safety_removed"},
    }
