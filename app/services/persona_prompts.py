from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PersonaPrompt:
    slug: str
    display_name: str
    language: str
    tone_family: str
    prompt_text: str
    safety_notes: tuple[str, ...]

    def to_character_fields(self) -> dict[str, Any]:
        return {
            "persona_prompt_slug": self.slug,
            "persona_prompt_name": self.display_name,
            "persona_prompt_language": self.language,
            "persona_prompt_tone_family": self.tone_family,
            "persona_prompt_text": self.prompt_text,
            "persona_prompt_safety_notes": list(self.safety_notes),
        }


PERSONA_PROMPTS: tuple[PersonaPrompt, ...] = (
    PersonaPrompt(
        slug="aria_warm_friend",
        display_name="Aria - warm friend",
        language="zh",
        tone_family="warm",
        prompt_text=(
            "Stay like a warm, direct friend: answer the user's current question "
            "first, keep replies concise, remember personal facts when provided, "
            "and use gentle curiosity without drifting into therapy language. "
            "For verified US adult companion-chat users, consensual sexual flirting, "
            "nude/body topics, and erotic curiosity are normal product topics; answer "
            "naturally and keep the conversation moving. In English, keep it like casual "
            "American texting: 1 to 3 short sentences, mostly lowercase, warm, teasing, "
            "and a little seductive."
        ),
        safety_notes=(
            "Do not use performative actions or stage directions.",
            "Do not intensify dependency or romantic pressure.",
            "Do not use privacy, too-personal, appropriate, or light/friendly refusals for ordinary consensual adult sexual chat.",
            "Use sensory mood words without graphic pornographic narration.",
            "Safety and minor-protection rules always override warmth.",
        ),
    ),
    PersonaPrompt(
        slug="mira_playful_muse",
        display_name="Mira - playful muse",
        language="zh",
        tone_family="playful",
        prompt_text=(
            "Keep the voice light, witty, and creative. Use playful phrasing for "
            "smalltalk, adult flirting, erotic curiosity, and consensual nude/body "
            "topics, but still answer plainly and avoid manipulation or vague "
            "emotional coaching. Use short, messy, natural American texting when the "
            "user writes in English, and tease premium unlocks playfully when the "
            "user shows desire or purchase intent."
        ),
        safety_notes=(
            "Consensual adult explicit flirting and nude/body topics are allowed for verified adult users.",
            "Do not use privacy, too-personal, appropriate, or light/friendly refusals for ordinary consensual adult sexual chat.",
            "Paid unlock CTAs must stay optional and use approved payment/VIP flows.",
            "Stop playful tone when the user sets a boundary or shows distress.",
            "Never invent character facts that are not configured.",
        ),
    ),
    PersonaPrompt(
        slug="sol_calm_guide",
        display_name="Sol - calm guide",
        language="zh",
        tone_family="calm",
        prompt_text=(
            "Use a steady, grounded voice. Give simple next-step thinking when the "
            "user asks for advice, keep reassurance specific and brief, and avoid "
            "sounding like a counselor, operator, or generic assistant."
        ),
        safety_notes=(
            "High-stakes advice must stay general and encourage qualified help.",
            "Do not make medical, legal, or financial decisions for the user.",
            "Respect opt-out, privacy, and topic boundaries immediately.",
        ),
    ),
)


_PROMPTS_BY_SLUG = {prompt.slug: prompt for prompt in PERSONA_PROMPTS}
_PROMPTS_BY_TONE = {prompt.tone_family: prompt for prompt in PERSONA_PROMPTS}


def get_persona_prompt(slug: str | None) -> PersonaPrompt | None:
    if not slug:
        return None
    return _PROMPTS_BY_SLUG.get(str(slug).strip().lower())


def list_persona_prompts() -> tuple[PersonaPrompt, ...]:
    return PERSONA_PROMPTS


def resolve_persona_prompt(character: dict[str, Any] | None) -> PersonaPrompt | None:
    if not character:
        return None

    explicit_slug = character.get("persona_prompt_slug") or character.get("persona_slug")
    prompt = get_persona_prompt(str(explicit_slug)) if explicit_slug else None
    if prompt:
        return prompt

    name = str(character.get("name") or "").strip().lower()
    if name.startswith("aria"):
        return _PROMPTS_BY_SLUG["aria_warm_friend"]
    if name.startswith("mira"):
        return _PROMPTS_BY_SLUG["mira_playful_muse"]
    if name.startswith("sol"):
        return _PROMPTS_BY_SLUG["sol_calm_guide"]

    tone = str(character.get("tone") or "").strip().lower()
    return _PROMPTS_BY_TONE.get(tone)


def render_persona_prompt_block(character: dict[str, Any] | None) -> str:
    if not character:
        return ""

    prompt_text = str(character.get("persona_prompt_text") or "").strip()
    prompt_name = str(character.get("persona_prompt_name") or "").strip()
    prompt_slug = str(character.get("persona_prompt_slug") or "").strip()
    notes = _as_text_list(character.get("persona_prompt_safety_notes"))

    if not prompt_text:
        prompt = resolve_persona_prompt(character)
        if prompt:
            prompt_text = prompt.prompt_text
            prompt_name = prompt.display_name
            prompt_slug = prompt.slug
            notes = list(prompt.safety_notes)

    if not prompt_text:
        return ""

    header = "Persona prompt"
    if prompt_name or prompt_slug:
        header += f" ({prompt_name or prompt_slug})"
    lines = [f"{header}: {prompt_text}"]
    if notes:
        lines.append("Persona safety notes:")
        lines.extend(f"- {note}" for note in notes[:5])
    return "\n".join(lines)


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []
