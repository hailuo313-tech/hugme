from __future__ import annotations

from services.persona_prompts import (
    get_persona_prompt,
    list_persona_prompts,
    render_persona_prompt_block,
    resolve_persona_prompt,
)
from services.prompt_builder import PromptInput, build_prompt


def test_catalog_has_at_least_three_active_personas():
    prompts = list_persona_prompts()

    assert len(prompts) >= 3
    assert {prompt.slug for prompt in prompts} >= {
        "aria_warm_friend",
        "mira_playful_muse",
        "sol_calm_guide",
    }
    assert all(prompt.prompt_text for prompt in prompts)


def test_resolves_persona_by_slug_name_and_tone():
    assert get_persona_prompt("aria_warm_friend").display_name.startswith("Aria")
    assert resolve_persona_prompt({"name": "Mira"}) == get_persona_prompt(
        "mira_playful_muse"
    )
    assert resolve_persona_prompt({"tone": "calm"}) == get_persona_prompt(
        "sol_calm_guide"
    )


def test_prompt_builder_injects_explicit_persona_prompt_into_l3():
    out = build_prompt(
        PromptInput(
            user_text="hi",
            character={
                "name": "Nova",
                "tone": "direct",
                "persona_prompt_slug": "nova_direct",
                "persona_prompt_name": "Nova - direct",
                "persona_prompt_text": "Use crisp, practical wording.",
                "persona_prompt_safety_notes": ["Never override L1 safety."],
            },
        )
    )

    body = out.layers["L3_CHARACTER"]
    assert "多人设 Prompt 覆盖规则" in body
    assert "Use crisp, practical wording." in body
    assert "Never override L1 safety." in body
    assert "L1_SAFETY" in out.system_content
    assert "L10_ANCHOR" in out.system_content


def test_prompt_builder_uses_catalog_fallback_for_known_persona_name():
    out = build_prompt(PromptInput(user_text="hi", character={"name": "Sol"}))

    body = out.layers["L3_CHARACTER"]
    assert "Sol - calm guide" in body
    assert "steady, grounded voice" in body


def test_empty_character_has_no_persona_prompt_block():
    assert render_persona_prompt_block(None) == ""
    out = build_prompt(PromptInput(user_text="hi", character=None))

    assert "多人设 Prompt 覆盖规则" not in out.layers["L3_CHARACTER"]
