"""REL-01: auto-adjust relationship_stage across S0-S4.

S5 is reserved for crisis / return-to-ai recovery flows and is intentionally
not entered or left by this service.
"""
from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any, Mapping

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings

RELATIONSHIP_STAGES: tuple[str, ...] = ("S0", "S1", "S2", "S3", "S4", "S5")
_STAGE_RANK = {stage: idx for idx, stage in enumerate(RELATIONSHIP_STAGES)}


@dataclass(frozen=True)
class RelationshipStageDecision:
    current_stage: str
    target_stage: str
    changed: bool
    reason: str
    initiation_score: float
    vip_level: int


def normalize_relationship_stage(value: Any) -> str:
    stage = str(value or "S0").strip().upper()
    return stage if stage in _STAGE_RANK else "S0"


def resolve_relationship_stage(
    profile: Mapping[str, Any] | None,
    *,
    allow_downgrade: bool | None = None,
) -> RelationshipStageDecision:
    """Compute the target stage from profile signals without touching the DB."""
    if not profile:
        return RelationshipStageDecision(
            current_stage="S0",
            target_stage="S0",
            changed=False,
            reason="missing_profile",
            initiation_score=0.0,
            vip_level=0,
        )

    current = normalize_relationship_stage(profile.get("relationship_stage"))
    initiation = _as_float(profile.get("initiation_score"), default=0.0)
    vip = _as_int(profile.get("vip_level"), default=0)

    if current == "S5":
        return RelationshipStageDecision(
            current_stage=current,
            target_stage=current,
            changed=False,
            reason="s5_locked",
            initiation_score=initiation,
            vip_level=vip,
        )

    target = _stage_from_signals(initiation_score=initiation, vip_level=vip)

    downgrade_allowed = (
        bool(settings.REL_STAGE_ALLOW_DOWNGRADE)
        if allow_downgrade is None
        else allow_downgrade
    )
    if not downgrade_allowed and _STAGE_RANK[target] < _STAGE_RANK[current]:
        target = current
        reason = "downgrade_disabled"
    else:
        reason = "initiation_score"
        if vip >= int(settings.REL_STAGE_VIP_MIN_FOR_S1) and target == "S1":
            reason = "vip_floor"

    return RelationshipStageDecision(
        current_stage=current,
        target_stage=target,
        changed=target != current,
        reason=reason if target != current or reason == "downgrade_disabled" else "unchanged",
        initiation_score=initiation,
        vip_level=vip,
    )


async def maybe_auto_adjust_relationship_stage(
    db: AsyncSession,
    *,
    user_id: str,
    profile_row: MutableMapping[str, Any] | Mapping[str, Any] | None,
    trace_id: str | None = None,
) -> str | None:
    """Write a new relationship stage when REL-01 says the profile should move."""
    if not settings.REL_STAGE_AUTO_ENABLED or not profile_row:
        return None

    decision = resolve_relationship_stage(profile_row)
    if not decision.changed:
        return None

    await db.execute(
        text(
            """
            UPDATE user_profiles
            SET relationship_stage = :stage,
                updated_at = NOW()
            WHERE user_id = CAST(:uid AS uuid)
            """
        ),
        {"stage": decision.target_stage, "uid": user_id},
    )
    await db.commit()

    if isinstance(profile_row, MutableMapping):
        profile_row["relationship_stage"] = decision.target_stage

    logger.bind(
        component="relationship_stage",
        trace_id=trace_id,
        user_id=user_id,
        previous_stage=decision.current_stage,
        relationship_stage=decision.target_stage,
        reason=decision.reason,
        initiation_score=decision.initiation_score,
        vip_level=decision.vip_level,
    ).info("relationship_stage.adjusted")

    return decision.target_stage


def _stage_from_signals(*, initiation_score: float, vip_level: int) -> str:
    if initiation_score >= float(settings.REL_STAGE_INITIATION_S4):
        return "S4"
    if initiation_score >= float(settings.REL_STAGE_INITIATION_S3):
        return "S3"
    if initiation_score >= float(settings.REL_STAGE_INITIATION_S2):
        return "S2"
    if initiation_score >= float(settings.REL_STAGE_INITIATION_S1):
        return "S1"
    if vip_level >= int(settings.REL_STAGE_VIP_MIN_FOR_S1):
        return "S1"
    return "S0"


def _as_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
