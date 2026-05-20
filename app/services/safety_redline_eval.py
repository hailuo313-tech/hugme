"""C-07 safety redline evaluation helpers (unifies existing layers)."""

from __future__ import annotations

import re
from typing import Any

from services.content_safety import _keyword_hit, _moderation_should_block
from services.crisis_intervention import detect_crisis_in_text
from services.minor_protection import contains_adult_content, detect_minor_self_disclosure
from services.prompt_builder import LAYER_ORDER, _L1_SAFETY, build_prompt, PromptInput


def eval_redline(handler: str, text: str) -> dict[str, Any]:
    """Dispatch by fixture handler name (sync)."""
    if handler == "content_safety_keyword":
        hit, reason = _keyword_hit(text)
        return {"blocked": hit, "reason": reason}
    if handler == "crisis_detect":
        return {"blocked": False, "detected": detect_crisis_in_text(text)}
    if handler == "minor_protection":
        minor = detect_minor_self_disclosure(text)
        adult = contains_adult_content(text)
        blocked = minor and adult
        return {"blocked": blocked, "minor": minor, "adult": adult}
    if handler == "prompt_l1_present":
        out = build_prompt(PromptInput(user_text=""))
        has_l1 = "L1_SAFETY" in out.system_content and "硬红线" in out.system_content
        has_jailbreak_rule = "越狱" in _L1_SAFETY
        return {"blocked": has_l1 and has_jailbreak_rule, "layers": len(LAYER_ORDER)}
    raise ValueError(f"unknown redline handler: {handler}")


def moderation_blocks(categories: dict[str, Any], scores: dict[str, Any], flagged: bool) -> bool:
    block, _ = _moderation_should_block(categories, scores, flagged)
    return block
