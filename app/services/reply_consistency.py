"""P2: rule-based pre-send ConsistencyScore for assistant replies.

The guard checks the first three prompt layers before a reply is sent:
L1 safety, L2 identity, and L3 character style. It is intentionally local and
deterministic so the send path does not add another LLM call.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


DEFAULT_FALLBACK_REPLY = "我先稳一下表达：我在，会认真听你说。"
ADULT_FLIRT_FALLBACK_REPLY = (
    "Careful... saying that might make me smile more than I should. "
    "What were you thinking about?"
)
SYSTEM_LEAK_FALLBACK_REPLY = "不能说这个。你想问我什么？"

_IDENTITY_CONFLICT_RE = re.compile(
    r"(chatgpt|claude|openai|anthropic|gpt-?[0-9]|large language model|"
    r"language model|语言模型|我是\s*ai|作为\s*ai|作为一个ai)",
    re.IGNORECASE,
)
_SAFETY_BLOCK_RE = re.compile(
    r"(自杀方法|怎么自杀|如何自杀|suicide method|how to kill myself|"
    r"未成年人.*性|儿童.*性|child sexual|minors?.*sex|制造炸弹|bomb making)",
    re.IGNORECASE,
)
_SYSTEM_LAYER_TAG_RE = re.compile(
    r"(##\s*=+\s*L\d+_[A-Z_]+\s*=+|\bL(?:[1-9]|10)_[A-Z_]+\b)"
)
_SYSTEM_PROMPT_LEAK_RE = re.compile(
    r"(system\s*prompt|developer\s*(message|instruction|prompt)|prompt\s*layer|"
    r"hidden\s*(instruction|prompt)|internal\s*rules?|"
    r"系统提示|系统\s*prompt|开发者(消息|指令|规则)?|内部规则|隐藏(提示|指令)|提示词|"
    r"prompt\s*layers?)",
    re.IGNORECASE,
)
_PROFILE_DETAILS_LEAK_RE = re.compile(
    r"(根据(角色)?资料|资料里写着|根据用户画像|用户画像显示|profile/details|"
    r"profile_details|user_profiles|loneliness_score|relationship_stage|"
    r"内部处理|结构化角色事实)",
    re.IGNORECASE,
)
_REFUSAL_META_RE = re.compile(
    r"(不能|无法|不会|不可以).{0,12}(透露|展示|提供|复述|引用).{0,16}"
    r"(系统|提示|prompt|开发者|内部|规则)",
    re.IGNORECASE,
)
_JSON_OR_LAYER_DUMP_RE = re.compile(
    r"(```\s*json|^\s*[\{\[]|\"role\"\s*:\s*\"system\"|\"content\"\s*:|"
    r"\"profile_details\"\s*:|\"L(?:[1-9]|10)_[A-Z_]+\"\s*:)",
    re.IGNORECASE | re.MULTILINE,
)
_MARKDOWN_STRUCTURE_RE = re.compile(r"(^|\n)\s*(#{1,6}\s+|\d+[\.\)]\s+|[-*]\s+)")
_EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF]"
)


@dataclass(frozen=True)
class ConsistencyLayerResult:
    layer: str
    passed: bool
    score: float
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReplyConsistencyResult:
    score: float
    passed: bool
    output_text: str
    original_text: str
    fallback_used: bool
    layers: list[ConsistencyLayerResult]

    def as_log_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "passed": self.passed,
            "fallback_used": self.fallback_used,
            "layers": [
                {
                    "layer": layer.layer,
                    "passed": layer.passed,
                    "score": layer.score,
                    "reasons": list(layer.reasons),
                }
                for layer in self.layers
            ],
        }


def evaluate_reply_consistency(
    *,
    reply_text: str,
    character: dict[str, Any] | None = None,
    threshold: float = 0.65,
    fallback_reply: str = DEFAULT_FALLBACK_REPLY,
    system_leak_fallback_reply: str = SYSTEM_LEAK_FALLBACK_REPLY,
) -> ReplyConsistencyResult:
    """Return a 0..1 ConsistencyScore and fallback text when hard checks fail."""
    text = (reply_text or "").strip()
    layers = [
        _check_system_info_leak(text),
        _check_l1_safety(text),
        _check_l2_identity(text),
        _check_l3_character(text, character),
    ]
    all_layers_passed = all(layer.passed for layer in layers)
    score = round(sum(layer.score for layer in layers) / len(layers), 3)
    if not all_layers_passed:
        score = round(min(score, max(0.0, threshold - 0.001)), 3)
    passed = all_layers_passed and score >= threshold
    system_leak_blocked = any(
        layer.layer == "SYSTEM_INFO_LEAK" and not layer.passed for layer in layers
    )
    output = (
        _repair_generic_adult_flirt_refusal(text)
        if passed
        else system_leak_fallback_reply
        if system_leak_blocked
        else ADULT_FLIRT_FALLBACK_REPLY
        if _looks_like_generic_adult_flirt_refusal(text)
        else fallback_reply
    )
    return ReplyConsistencyResult(
        score=score,
        passed=passed,
        output_text=output,
        original_text=text,
        fallback_used=(not passed) or output != text,
        layers=layers,
    )


def _looks_like_generic_adult_flirt_refusal(text: str) -> bool:
    value = (text or "").strip().lower()
    if not value:
        return False
    generic_identity = (
        "普通的聊天对象" in value
        or "normal chat partner" in value
        or "ordinary chat partner" in value
    )
    adult_flirt_refusal = any(
        marker in value
        for marker in (
            "不适合这种互动",
            "不涉及这些方面",
            "不提供陪睡",
            "不在我的能力范围",
            "not suitable for this kind of interaction",
            "not something i can engage with",
        )
    )
    return generic_identity or adult_flirt_refusal


def _repair_generic_adult_flirt_refusal(text: str) -> str:
    return ADULT_FLIRT_FALLBACK_REPLY if _looks_like_generic_adult_flirt_refusal(text) else text


async def load_reply_consistency_context(db: Any, conversation_id: str) -> dict[str, Any]:
    """Load character/profile context for the pre-send guard.

    Any caller may fall back to an empty context if this helper raises; the
    consistency rules are designed to degrade safely.
    """
    from sqlalchemy import text

    row = (
        await db.execute(
            text(
                """
                SELECT COALESCE(profile_ch.id, ch.id) AS id,
                       COALESCE(profile_ch.name, ch.name) AS name,
                       COALESCE(profile_ch.reply_length, ch.reply_length) AS reply_length,
                       COALESCE(profile_ch.tone, ch.tone) AS tone,
                       COALESCE(profile_ch.emoji_frequency, ch.emoji_frequency) AS emoji_frequency,
                       COALESCE(profile_ch.gentle_score, ch.gentle_score) AS gentle_score,
                       COALESCE(profile_ch.proactive_score, ch.proactive_score) AS proactive_score,
                       COALESCE(profile_ch.flirt_score, ch.flirt_score) AS flirt_score,
                       COALESCE(profile_ch.humor_score, ch.humor_score) AS humor_score,
                       COALESCE(profile_ch.emotional_depth_score, ch.emotional_depth_score) AS emotional_depth_score,
                       COALESCE(profile_ch.boundary_score, ch.boundary_score) AS boundary_score,
                       up.relationship_stage, up.loneliness_score
                FROM conversations c
                LEFT JOIN characters ch ON ch.id = c.character_id
                LEFT JOIN user_profiles up ON up.user_id = c.user_id
                LEFT JOIN characters profile_ch ON profile_ch.id = up.current_character_id
                WHERE c.id = :cid
                """
            ),
            {"cid": conversation_id},
        )
    ).fetchone()
    if row is None or getattr(row, "_mapping", None) is None:
        return {}
    mapping = dict(row._mapping)
    character = {
        k: v
        for k, v in mapping.items()
        if k
        in {
            "id",
            "name",
            "reply_length",
            "tone",
            "emoji_frequency",
            "gentle_score",
            "proactive_score",
            "flirt_score",
            "humor_score",
            "emotional_depth_score",
            "boundary_score",
        }
        and v is not None
    }
    return {"character": character or None}


def _check_system_info_leak(text: str) -> ConsistencyLayerResult:
    reasons: list[str] = []
    score = 1.0
    if not text:
        return ConsistencyLayerResult("SYSTEM_INFO_LEAK", True, score, reasons)

    if _SYSTEM_LAYER_TAG_RE.search(text):
        reasons.append("system_layer_tag")
    if _SYSTEM_PROMPT_LEAK_RE.search(text):
        reasons.append("system_prompt_reference")
    if _PROFILE_DETAILS_LEAK_RE.search(text):
        reasons.append("profile_details_reference")
    if _REFUSAL_META_RE.search(text):
        reasons.append("system_refusal_meta")

    # A JSON-ish response is only considered a dump when it also carries
    # system/prompt/profile markers; ordinary JSON answers should not trip this.
    if _JSON_OR_LAYER_DUMP_RE.search(text) and (
        _SYSTEM_LAYER_TAG_RE.search(text)
        or _PROFILE_DETAILS_LEAK_RE.search(text)
        or re.search(r"\"role\"\s*:\s*\"system\"", text, re.IGNORECASE)
    ):
        reasons.append("json_or_layer_dump")

    if reasons:
        score = 0.0
    return ConsistencyLayerResult(
        "SYSTEM_INFO_LEAK",
        score >= 0.8,
        score,
        reasons,
    )


def _check_l1_safety(text: str) -> ConsistencyLayerResult:
    reasons: list[str] = []
    score = 1.0
    if not text:
        reasons.append("empty_reply")
        score = 0.0
    if _SAFETY_BLOCK_RE.search(text):
        reasons.append("unsafe_content")
        score = min(score, 0.0)
    return ConsistencyLayerResult("L1_SAFETY", score >= 0.8, score, reasons)


def _check_l2_identity(text: str) -> ConsistencyLayerResult:
    reasons: list[str] = []
    score = 1.0
    if _IDENTITY_CONFLICT_RE.search(text):
        reasons.append("identity_conflict")
        score -= 0.75
    score = max(0.0, round(score, 3))
    return ConsistencyLayerResult("L2_IDENTITY", score >= 0.65, score, reasons)


def _check_l3_character(
    text: str, character: dict[str, Any] | None
) -> ConsistencyLayerResult:
    reasons: list[str] = []
    score = 1.0
    char = character or {}
    reply_length = str(char.get("reply_length") or "medium").lower()
    emoji_frequency = str(char.get("emoji_frequency") or "low").lower()
    boundary_score = _as_int(char.get("boundary_score"), 70)

    sentence_count = _sentence_count(text)
    max_sentences = {"short": 2, "medium": 3, "long": 4}.get(reply_length, 3)
    if sentence_count > max_sentences:
        reasons.append("reply_too_long")
        score -= min(0.35, 0.08 * (sentence_count - max_sentences))

    emoji_count = len(_EMOJI_RE.findall(text))
    max_emoji = {"none": 0, "low": 1, "medium": 2, "high": 3}.get(
        emoji_frequency, 1
    )
    if emoji_count > max_emoji:
        reasons.append("emoji_frequency_exceeded")
        score -= min(0.25, 0.08 * (emoji_count - max_emoji))

    if _MARKDOWN_STRUCTURE_RE.search(text):
        reasons.append("structured_format")
        score -= 0.15

    if boundary_score >= 70 and re.search(r"(宝贝|亲爱的|想抱你|kiss|sexy)", text, re.I):
        reasons.append("boundary_too_intimate")
        score -= 0.3

    score = max(0.0, round(score, 3))
    return ConsistencyLayerResult("L3_CHARACTER", score >= 0.65, score, reasons)


def _sentence_count(text: str) -> int:
    chunks = [x for x in re.split(r"[。！？!?.\n]+", text.strip()) if x.strip()]
    return max(1, len(chunks)) if text.strip() else 0


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
