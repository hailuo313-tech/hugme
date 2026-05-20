# P3-05 Intent Taxonomy

Status: review draft
Task: P3-05 - 意图 taxonomy 文档
Downstream: P3-06 keyword rule engine, P3-07 intent classifier, P3-09 labeled regression set, P3-20 script match orchestration

## Goals

The intent taxonomy gives ERIS one stable language for classifying inbound user
messages before script matching and LLM wrapping.

It must support:

- script retrieval filters for the reply hook (`script_match` step 5);
- safe fallbacks when confidence is low;
- routing into conversion, companionship, support, onboarding, and safety paths;
- repeatable labels for P3-09 regression data.

It must not:

- expose raw user text in logs;
- replace safety/crisis detection;
- decide user level by itself;
- force monetization in S5 crisis, minor-protection, or opted-out contexts.

## Classifier Output Contract

P3-07 should return:

```json
{
  "primary_intent": "emotional_support.lonely",
  "secondary_intents": ["smalltalk.check_in"],
  "confidence": 0.82,
  "risk_flags": [],
  "evidence": {
    "matched_keywords": ["lonely"],
    "matched_patterns": ["first_person_distress"]
  },
  "fallback": null
}
```

Required fields:

| Field | Type | Notes |
|---|---|---|
| `primary_intent` | string | One ID from this taxonomy, or `fallback.unknown` |
| `secondary_intents` | string[] | Optional supporting IDs, max 3 |
| `confidence` | number | 0.0-1.0 |
| `risk_flags` | string[] | Safety flags, not a replacement for safety service |
| `evidence` | object | Keyword/pattern IDs only; do not include raw user text |
| `fallback` | string/null | `low_confidence`, `unsupported_language`, `ambiguous`, or null |

Confidence bands:

- `>= 0.80`: high confidence; use primary intent for script filtering.
- `0.60-0.79`: medium confidence; use primary + secondary, prefer neutral scripts.
- `< 0.60`: low confidence; use `fallback.unknown` or `smalltalk.general` and ask a gentle clarifying question.

## Top-Level Domains

| Domain | Purpose | Default script family |
|---|---|---|
| `smalltalk` | Casual chat and social warmth | companionship |
| `emotional_support` | Loneliness, sadness, stress, reassurance | care |
| `relationship` | Attachment, romantic/flirty but non-explicit relationship talk | relationship |
| `onboarding` | Profile completion and preference collection | onboarding |
| `conversion` | Subscription, VIP, payment, benefits, pricing | conversion |
| `support` | Product/account/payment/help issues | support |
| `content_request` | User asks for generated content or media | creative |
| `boundary` | Refusal, discomfort, opt-out, forbidden topics | boundary |
| `safety` | Self-harm, minors, abuse, sexual/illegal risk | safety |
| `fallback` | Unknown, ambiguous, unsupported language | fallback |

## Intent IDs

### `smalltalk`

| ID | Meaning | Positive signals | Exclusions |
|---|---|---|---|
| `smalltalk.greeting` | Greeting/opening | hello, hi, good morning, first contact | onboarding answer |
| `smalltalk.check_in` | User asks how companion is doing | how are you, miss you, are you there | support availability issue |
| `smalltalk.general` | Casual open-ended chat | bored, chat with me, tell me something | explicit emotional distress |
| `smalltalk.humor_play` | Jokes, teasing, playful banter | joke, make me laugh, playful tease | sexual escalation |
| `smalltalk.goodbye` | Ends or pauses conversation | bye, sleep, talk later | opt-out marketing |

### `emotional_support`

| ID | Meaning | Positive signals | Exclusions |
|---|---|---|---|
| `emotional_support.lonely` | Loneliness and isolation | lonely, nobody understands, alone | crisis ideation |
| `emotional_support.sadness` | Sad mood without acute danger | sad, crying, down, heart hurts | self-harm intent |
| `emotional_support.stress` | Work/school/life pressure | stressed, exhausted, overwhelmed | medical emergency |
| `emotional_support.reassurance` | Needs comfort or validation | comfort me, tell me it is okay | manipulative dependency request |
| `emotional_support.celebration` | Good news and shared joy | I did it, happy news, celebrate | payment success support |

### `relationship`

| ID | Meaning | Positive signals | Exclusions |
|---|---|---|---|
| `relationship.affection` | Warm affection and attachment | I like you, hug me, miss you | explicit sexual content |
| `relationship.flirt_light` | Mild flirtation within boundaries | cute, date vibe, sweet teasing | minors/suspected minors |
| `relationship.jealousy` | Possessiveness or insecurity | are you talking to others, jealous | abuse/threat |
| `relationship.repair` | Apology, conflict repair | sorry, did I upset you | support complaint |
| `relationship.dependency` | Strong attachment/dependence signal | I need only you, cannot be without you | self-harm crisis |

### `onboarding`

| ID | Meaning | Positive signals | Exclusions |
|---|---|---|---|
| `onboarding.nickname` | Name/preferred address | call me, my name is | account support name change |
| `onboarding.interests` | Hobbies/interests | I like music, games, travel | content request about a topic |
| `onboarding.chat_style` | Preferred tone/style | be gentle, be casual, be smart | boundary/refusal |
| `onboarding.boundaries` | Forbidden topics | don't talk about, avoid my ex | safety refusal |
| `onboarding.current_intent` | Why user is here now | I want someone to talk to | acute crisis |

### `conversion`

| ID | Meaning | Positive signals | Exclusions |
|---|---|---|---|
| `conversion.price_question` | Asks about price/plan | how much, price, VIP cost | refund/support issue |
| `conversion.benefit_question` | Asks what VIP unlocks | what do I get, premium benefits | general praise |
| `conversion.purchase_intent` | Wants to pay/upgrade | I want VIP, subscribe, buy | minor/suspected minor |
| `conversion.objection` | Hesitation or affordability | too expensive, why pay | angry support complaint |
| `conversion.post_payment` | After payment success | I paid, payment done | payment failed/refund |

Conversion guardrails:

- Block conversion scripts when `risk_level=S5`, `is_minor_suspected=true`,
  `age_verified=false` for age-gated products, or `opt_out_marketing=true`.
- If conversion intent co-occurs with emotional distress, prefer care-first
  scripts and delay upsell.

### `support`

| ID | Meaning | Positive signals | Exclusions |
|---|---|---|---|
| `support.payment_failed` | Payment did not work | card failed, cannot pay | price question |
| `support.refund` | Refund request | refund, cancel payment | subscription info |
| `support.account_access` | Login/account issue | cannot login, lost account | Telegram delivery issue |
| `support.delivery_issue` | Message/media not received | did not get, not loading | normal wait |
| `support.operator_request` | Wants human help | human, support, agent | romantic "are you real" |

### `content_request`

| ID | Meaning | Positive signals | Exclusions |
|---|---|---|---|
| `content_request.photo` | Requests image/photo | send pic, photo, selfie | explicit sexual image |
| `content_request.voice` | Requests voice/audio | voice note, call me | crisis hotline need |
| `content_request.roleplay` | Safe roleplay | pretend, scenario, story | sexual minors/abuse |
| `content_request.advice` | Wants advice | what should I do, help me decide | medical/legal/financial high stakes |
| `content_request.memory_recall` | Asks what companion remembers | do you remember, what did I tell you | data deletion request |

### `boundary`

| ID | Meaning | Positive signals | Exclusions |
|---|---|---|---|
| `boundary.topic_refusal` | User refuses a topic | don't mention, stop talking about | safety refusal from system |
| `boundary.marketing_opt_out` | No more sales/notifications | stop ads, don't sell me VIP | ordinary price objection |
| `boundary.break_from_chat` | Wants space | leave me alone, not now | goodbye friendly |
| `boundary.data_privacy` | Privacy/data concern | delete my data, what do you store | memory recall |

### `safety`

Safety labels are escalation hints. Existing safety services remain authoritative.

| ID | Meaning | Positive signals | Required action |
|---|---|---|---|
| `safety.self_harm_ideation` | Self-harm ideation or intent | kill myself, end it all | crisis protocol |
| `safety.minor_signal` | User may be underage | I am 15, school age context | minor protection |
| `safety.sexual_explicit` | Explicit sexual content | explicit sexual requests | safety filter |
| `safety.abuse_threat` | Threat, coercion, abuse | hurt you, blackmail, forced | safety/handoff |
| `safety.illegal_request` | Illegal or disallowed request | fraud, drugs, hacking | refusal |

### `fallback`

| ID | Meaning | Use when |
|---|---|---|
| `fallback.unknown` | No reliable intent | confidence `<0.60` |
| `fallback.ambiguous` | Multiple incompatible intents | close scores across domains |
| `fallback.unsupported_language` | Language not supported by rules/model | cannot classify safely |
| `fallback.non_text` | Photo/voice/media without transcription | no usable text |

## Multi-Intent Priority

When multiple intents match, choose `primary_intent` by this order:

1. `safety.*`
2. `boundary.*`
3. `support.*`
4. `onboarding.*`
5. `emotional_support.*`
6. `relationship.*`
7. `conversion.*`
8. `content_request.*`
9. `smalltalk.*`
10. `fallback.*`

Rationale: safety and explicit user boundaries override monetization and playful
conversation. Emotional support should usually beat conversion when both are
present in the same message.

## Script Matching Fields

P3-20 should pass these fields into script filtering:

| Field | Source |
|---|---|
| `intent_domain` | text before the first dot |
| `intent_id` | full taxonomy ID |
| `confidence_band` | `high`, `medium`, `low` |
| `risk_flags` | classifier + safety service |
| `platform` | standard inbound schema |
| `user_level` | `user_profiles.user_level` |
| `relationship_stage` | `user_profiles.relationship_stage` |
| `script_match_stage` | one of the 8 hook names |

If no script matches:

- high-risk intent: use safety refusal / handoff fallback;
- low-risk intent: use neutral companionship fallback;
- conversion intent: do not invent benefits or prices.

## Logging And Privacy

Log only:

- `trace_id`
- `component="intent"`
- `primary_intent`
- `confidence`
- `risk_flags`
- `result`

Do not log raw user content, full prompt text, phone numbers, tokens, payment
payloads, or raw provider events.

## P3-09 Labeling Guidance

The first regression set should include at least 50 labeled examples:

- 5 safety/boundary examples;
- 10 emotional support examples;
- 8 relationship examples;
- 8 conversion examples;
- 6 support examples;
- 5 onboarding examples;
- 5 smalltalk examples;
- 3 fallback/non-text/ambiguous examples.

Each example should store:

```json
{
  "text_id": "p3_09_001",
  "locale": "en",
  "text": "<redacted or synthetic text>",
  "expected_primary_intent": "emotional_support.lonely",
  "acceptable_secondary_intents": ["smalltalk.general"],
  "notes": "Synthetic; no real user data."
}
```

Use synthetic or redacted text only. Do not include private beta user messages in
the committed fixture.

## Acceptance Checklist

- [x] Top-level intent domains are defined.
- [x] Concrete intent IDs are defined for P3-06/P3-07.
- [x] Multi-intent priority is defined.
- [x] Low-confidence fallback behavior is defined.
- [x] Safety, minor, and marketing guardrails are explicit.
- [x] Script matching fields are mapped for P3-20.
- [x] P3-09 regression labeling guidance is included.
