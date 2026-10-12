"""Sanitize conversation history before it is injected into LLM prompts."""

from __future__ import annotations

import re

from services.link_cooldown import strip_links_from_reply

_PHOTO_GARNISH_RE = re.compile(
    r"(?:"
    r"My lens[^.?\n]*[.?\n]?"
    r"|My studio[^.?\n]*[.?\n]?"
    r"|(?:floor-to-ceiling )?studio[^.?\n]*[.?\n]?"
    r"|photography backdrops?[^.?\n]*[.?\n]?"
    r"|liquid gold at night[^.?\n]*[.?\n]?"
    r"|golden hour[^.?\n]*[.?\n]?"
    r"|left to your imagination[^.?\n]*[.?\n]?"
    r")",
    re.IGNORECASE,
)
_DEFLECTION_SENTENCE_RE = re.compile(
    r"(?:"
    r"I prefer keeping things (?:light|meaningful)[^.?\n]*[.?\n]"
    r"|keep(?:ing)? (?:our )?conversations? focused on shared interests[^.?\n]*[.?\n]"
    r"|let'?s talk about (?:films?|photography|coffee|that new coffee spot)[^.?\n]*[.?\n]"
    r"|(?:as for )?personal topics?,? I keep[^.?\n]*[.?\n]"
    r"|that'?s (?:a little )?too personal[^.?\n]*[.?\n]"
    r"|my sex life is private[^.?\n]*[.?\n]"
    r"|I don'?t share photos?[^.?\n]*[.?\n]"
    r"|I can'?t send (?:pics?|photos?|nudes?)[^.?\n]*[.?\n]"
    r"|I don'?t discuss that[^.?\n]*[.?\n]"
    r"|I(?:'d| would) rather keep (?:this|things) (?:light|friendly)[^.?\n]*[.?\n]"
    r"|instead,? let'?s (?:talk|chat) about[^.?\n]*[.?\n]"
    r")",
    re.IGNORECASE,
)

_DEFLECTION_MARKERS = (
    "prefer keeping things light",
    "too personal",
    "my sex life is private",
    "i don't share photos",
    "i don't share photo",
    "i can't send pics",
    "i can't send photos",
    "keep conversations focused on shared interests",
    "let's talk about films",
    "let's talk about photography",
    "talk about photography",
    "coffee spot downtown",
    "my lens",
    "left to your imagination",
    "photography backdrops",
)


def is_deflection_heavy_content(text_value: str) -> bool:
    """True when assistant history is mostly a refusal/deflection template."""
    if not text_value:
        return False
    lowered = text_value.lower()
    hits = sum(1 for marker in _DEFLECTION_MARKERS if marker in lowered)
    if hits >= 2:
        return True
    if hits >= 1 and len(text_value.strip()) < 220:
        return True
    return False


def sanitize_history_message_for_prompt(
    role: str,
    content: str,
) -> str | None:
    """Return cleaned history content, or None to drop the message entirely."""
    if role != "assistant":
        return content

    cleaned = strip_links_from_reply(content)
    cleaned = _PHOTO_GARNISH_RE.sub("", cleaned)
    cleaned = _DEFLECTION_SENTENCE_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if not cleaned:
        return None
    if is_deflection_heavy_content(cleaned):
        return None
    return cleaned
