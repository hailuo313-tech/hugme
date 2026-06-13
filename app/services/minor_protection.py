"""Minor protection gate removed — always pass through (pending rewrite)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

MINOR_BLOCK_DETAIL = "Minor protection removed"
AGE_VERIFICATION_REQUIRED_DETAIL = "Age verification removed"


@dataclass(frozen=True)
class MinorProtectionDecision:
    blocked: bool
    reason: str | None
    suspected_minor: bool
    adult_content: bool
    updated_user: bool = False

    def as_safety_layer(self) -> dict[str, Any]:
        return {
            "blocked": False,
            "block_reason": None,
            "minor_protection": {
                "skipped": True,
                "reason": "minor_protection_removed",
            },
        }


def detect_minor_self_disclosure(text_value: str) -> bool:
    return False


def contains_adult_content(text_value: str) -> bool:
    return False


def should_block_consumption(*, age_verified: bool, is_minor_suspected: bool) -> str | None:
    return None


def should_block_push(*, is_minor_suspected: bool) -> str | None:
    return None


async def evaluate_inbound_minor_protection(
    db: AsyncSession,
    *,
    user_id: str,
    text_value: str,
    is_minor_suspected: bool,
) -> MinorProtectionDecision:
    return MinorProtectionDecision(
        blocked=False,
        reason=None,
        suspected_minor=False,
        adult_content=False,
        updated_user=False,
    )
