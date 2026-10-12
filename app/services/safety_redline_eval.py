"""C-07 safety redline helpers — all gates removed (pending rewrite)."""

from __future__ import annotations

from typing import Any


def eval_redline(handler: str, text: str) -> dict[str, Any]:
    if handler == "minor_protection":
        return {"blocked": False, "minor": False, "adult": False}
    if handler == "crisis_detect":
        return {"blocked": False, "detected": False}
    if handler == "content_safety_keyword":
        return {"blocked": False, "reason": None}
    if handler == "prompt_l1_present":
        return {"blocked": False, "layers": 0}
    raise ValueError(f"unknown redline handler: {handler}")


def moderation_blocks(categories: dict[str, Any], scores: dict[str, Any], flagged: bool) -> bool:
    return False
