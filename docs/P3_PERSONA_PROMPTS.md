# P3-10 Persona Prompts

Status: review draft
Task: P3-10 - persona_prompts 多人设 Prompt

## Goals

`persona_prompts` gives ERIS a reusable prompt catalog for character voices.
Characters still own factual identity fields such as name, age, city, occupation,
and profile details. Persona prompts only shape delivery style and interaction
boundaries.

## Storage Contract

The `persona_prompts` table is created by
`scripts/migrations/p3_persona_prompts.sql`.

Required fields:

| Field | Purpose |
|---|---|
| `slug` | Stable prompt key used by admin/config |
| `display_name` | Human-readable persona name |
| `language` | Default prompt language |
| `tone_family` | Routing hint such as `warm`, `playful`, `calm` |
| `prompt_text` | Style instruction injected into L3_CHARACTER |
| `safety_notes` | JSON array of persona-specific guardrails |
| `status` | `active`, `draft`, or `archived` |

`characters.persona_prompt_id` may point to one active persona prompt. When a
runtime character row already includes `persona_prompt_text`, Prompt Builder uses
that value. Otherwise it can resolve the built-in catalog by slug, character
name, or tone.

## Baseline Personas

| Slug | Display name | Tone | Intended use |
|---|---|---|---|
| `aria_warm_friend` | Aria - warm friend | warm | General companionship and gentle direct answers |
| `mira_playful_muse` | Mira - playful muse | playful | Safe banter, creativity, light relationship talk |
| `sol_calm_guide` | Sol - calm guide | calm | Grounded advice and steady low-drama support |

## Prompt Injection Rules

- Inject persona instructions only inside `L3_CHARACTER`.
- Do not replace `L1_SAFETY`, `L2_IDENTITY`, `L9_FORMAT`, or `L10_ANCHOR`.
- Persona prompts must not include raw user data, secrets, pricing, or hidden
  policy text.
- Persona prompts may adjust tone, length preference, creativity, and boundary
  reminders.
- Safety, minor protection, opt-out, S5 crisis recovery, and script-match
  constraints always override persona tone.

## Acceptance Checklist

- [x] `persona_prompts` table contract exists.
- [x] At least three baseline personas are defined.
- [x] Prompt Builder can inject persona guidance into `L3_CHARACTER`.
- [x] Fallback resolution works without requiring a database join.
- [x] Persona prompts do not override safety or internal-rule protections.
