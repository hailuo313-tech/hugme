"""Human-like delay calculator for P3-14."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class HumanDelayPolicy:
    min_delay_seconds: float = 2.0
    max_delay_seconds: float = 18.0
    base_seconds: float = 1.2
    seconds_per_word: float = 0.38
    seconds_per_cjk_char: float = 0.11
    punctuation_pause_seconds: float = 0.35
    media_extra_seconds: float = 2.5


@dataclass(frozen=True)
class HumanDelayResult:
    delay_seconds: float
    word_count: int
    cjk_char_count: int
    punctuation_count: int
    clamped: bool


DEFAULT_HUMAN_DELAY_POLICY = HumanDelayPolicy()


def calculate_human_delay(
    text: str,
    *,
    has_media: bool = False,
    policy: HumanDelayPolicy = DEFAULT_HUMAN_DELAY_POLICY,
) -> HumanDelayResult:
    value = text or ""
    word_count = len(re.findall(r"[A-Za-z0-9']+", value))
    cjk_char_count = len([ch for ch in value if "\u4e00" <= ch <= "\u9fff"])
    punctuation_count = len(re.findall(r"[,.!?;:，。！？；：]", value))
    raw = (
        policy.base_seconds
        + word_count * policy.seconds_per_word
        + cjk_char_count * policy.seconds_per_cjk_char
        + punctuation_count * policy.punctuation_pause_seconds
        + (policy.media_extra_seconds if has_media else 0.0)
    )
    delay = min(policy.max_delay_seconds, max(policy.min_delay_seconds, raw))
    return HumanDelayResult(
        delay_seconds=round(delay, 2),
        word_count=word_count,
        cjk_char_count=cjk_char_count,
        punctuation_count=punctuation_count,
        clamped=delay != raw,
    )
