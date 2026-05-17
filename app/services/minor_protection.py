from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


MINOR_BLOCK_DETAIL = "Minor protection restriction"
AGE_VERIFICATION_REQUIRED_DETAIL = "Age verification required"

_MINOR_DISCLOSURE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:i'?m|i am|im)\s*(?:only\s*)?(?:1[0-7]|[1-9])\s*(?:years?\s*old|yo|y/o)\b", re.I),
    re.compile(r"\b(?:1[0-7]|[1-9])\s*(?:years?\s*old|yo|y/o)\b", re.I),
    re.compile(
        r"(?:我|俺)?\s*(?:才|只有)?\s*"
        r"(?:[1-9]|1[0-7]|[一二三四五六七八九]|十|十一|十二|十三|十四|十五|十六|十七)\s*岁",
        re.I,
    ),
    re.compile(r"(未成年|未滿十八|未满十八|初中生|小学生|中学生)", re.I),
)

_ADULT_CONTENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(sex|sexy|nude|nudes|porn|horny|erotic|dirty talk|hook up)\b", re.I),
    re.compile(r"(裸照|色情|做爱|做愛|约炮|約炮|性聊|开房|開房|下流)", re.I),
)


@dataclass(frozen=True)
class MinorProtectionDecision:
    blocked: bool
    reason: str | None
    suspected_minor: bool
    adult_content: bool
    updated_user: bool = False

    def as_safety_layer(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "block_reason": self.reason,
            "minor_protection": {
                "suspected_minor": self.suspected_minor,
                "adult_content": self.adult_content,
                "updated_user": self.updated_user,
            },
        }


def detect_minor_self_disclosure(text_value: str) -> bool:
    text_value = (text_value or "").strip()
    return bool(text_value and any(pattern.search(text_value) for pattern in _MINOR_DISCLOSURE_PATTERNS))


def contains_adult_content(text_value: str) -> bool:
    text_value = (text_value or "").strip()
    return bool(text_value and any(pattern.search(text_value) for pattern in _ADULT_CONTENT_PATTERNS))


def should_block_consumption(*, age_verified: bool, is_minor_suspected: bool) -> str | None:
    if is_minor_suspected:
        return "minor_suspected"
    if not age_verified:
        return "age_not_verified"
    return None


def should_block_push(*, is_minor_suspected: bool) -> str | None:
    if is_minor_suspected:
        return "minor_suspected"
    return None


async def evaluate_inbound_minor_protection(
    db: AsyncSession,
    *,
    user_id: str,
    text_value: str,
    is_minor_suspected: bool,
) -> MinorProtectionDecision:
    disclosed_minor = detect_minor_self_disclosure(text_value)
    adult_content = contains_adult_content(text_value)
    suspected = bool(is_minor_suspected or disclosed_minor)
    updated = False

    if disclosed_minor and not is_minor_suspected:
        await db.execute(
            text(
                """
                UPDATE users
                SET is_minor_suspected = TRUE,
                    notification_opt_in = FALSE,
                    opt_out_marketing = TRUE,
                    updated_at = NOW()
                WHERE id = :uid
                """
            ),
            {"uid": user_id},
        )
        await db.commit()
        updated = True

    blocked = suspected and adult_content
    return MinorProtectionDecision(
        blocked=blocked,
        reason="minor_protection:adult_content" if blocked else None,
        suspected_minor=suspected,
        adult_content=adult_content,
        updated_user=updated,
    )
