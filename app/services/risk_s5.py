"""RISK-S5：关系阶段 S5（危机后）行为限制。

产品规则（§3.4 / backlog RISK-S5）
---------------------------------
- **禁 Upsell**：S5 期间 AI / 运营不得推销、付费引导、VIP 升级话术。
- **48–72h 关怀节奏**：仅该时间窗可排程 ``s5_care_checkin`` 类触达；其余营销/召回禁止。
- **7 天恢复**：自危机 risk_event 起满 7 天后可 ``return-ai`` 并将阶段降为 S4。

锚点时间：最近一条 ``risk_events.risk_type='crisis'`` 的 ``created_at``；
若无记录则回退 ``user_profiles.updated_at``。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

CARE_MIN_HOURS = 48.0
CARE_MAX_HOURS = 72.0
RECOVERY_DAYS = 7.0

MARKETING_NOTIFICATION_TYPES = frozenset(
    {"silent_reactivation", "marketing", "upsell", "promo", "promotion"}
)
S5_CARE_NOTIFICATION_TYPE = "s5_care_checkin"
RECOVERY_TARGET_STAGE = "S4"


class S5Phase(str, Enum):
    ACUTE = "acute"
    CARE_WINDOW = "care_window"
    STABILIZATION = "stabilization"
    RECOVERY_ELIGIBLE = "recovery_eligible"


@dataclass(frozen=True)
class S5Restrictions:
    active: bool
    phase: S5Phase | None
    entered_at: datetime | None
    hours_since_entry: float | None

    @property
    def upsell_allowed(self) -> bool:
        return not self.active

    @property
    def marketing_notifications_allowed(self) -> bool:
        return not self.active

    @property
    def care_notifications_allowed(self) -> bool:
        return self.active and self.phase == S5Phase.CARE_WINDOW

    @property
    def recovery_eligible(self) -> bool:
        return self.active and self.phase == S5Phase.RECOVERY_ELIGIBLE


def relationship_stage_is_s5(profile: Mapping[str, Any] | None) -> bool:
    if not profile:
        return False
    return (str(profile.get("relationship_stage") or "S0").strip().upper()) == "S5"


def compute_s5_phase(entered_at: datetime, now: datetime) -> S5Phase:
    hours = max(0.0, (now - entered_at).total_seconds() / 3600.0)
    days = hours / 24.0
    if hours < CARE_MIN_HOURS:
        return S5Phase.ACUTE
    if hours < CARE_MAX_HOURS:
        return S5Phase.CARE_WINDOW
    if days < RECOVERY_DAYS:
        return S5Phase.STABILIZATION
    return S5Phase.RECOVERY_ELIGIBLE


async def fetch_s5_entered_at(db: AsyncSession, user_id: str) -> datetime | None:
    row = (
        await db.execute(
            text(
                """
                SELECT created_at
                FROM risk_events
                WHERE user_id = :uid AND risk_type = 'crisis'
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"uid": user_id},
        )
    ).fetchone()
    if row and row[0] is not None:
        return row[0]
    return None


async def load_s5_restrictions(
    db: AsyncSession,
    *,
    user_id: str,
    profile: Mapping[str, Any] | None,
    now: datetime | None = None,
) -> S5Restrictions:
    if not relationship_stage_is_s5(profile):
        return S5Restrictions(
            active=False, phase=None, entered_at=None, hours_since_entry=None
        )

    now_utc = (now or datetime.utcnow()).replace(tzinfo=None)
    entered_at = await fetch_s5_entered_at(db, user_id)
    if entered_at is None and profile is not None:
        entered_at = profile.get("updated_at")
    if entered_at is None:
        entered_at = now_utc
    if hasattr(entered_at, "replace") and getattr(entered_at, "tzinfo", None):
        entered_at = entered_at.replace(tzinfo=None)

    hours = max(0.0, (now_utc - entered_at).total_seconds() / 3600.0)
    phase = compute_s5_phase(entered_at, now_utc)
    return S5Restrictions(
        active=True,
        phase=phase,
        entered_at=entered_at,
        hours_since_entry=hours,
    )


def notification_block_reason(
    restrictions: S5Restrictions,
    notification_type: str,
) -> str | None:
    if not restrictions.active:
        return None

    ntype = (notification_type or "").strip().lower()
    if ntype in MARKETING_NOTIFICATION_TYPES:
        return f"S5: {ntype} notifications are blocked"

    if ntype == S5_CARE_NOTIFICATION_TYPE:
        if restrictions.care_notifications_allowed:
            return None
        return "S5: care check-in only allowed between 48h and 72h after crisis"

    if restrictions.phase in (S5Phase.ACUTE, S5Phase.STABILIZATION):
        return f"S5: proactive {ntype} blocked outside 48-72h care window"
    if restrictions.phase == S5Phase.CARE_WINDOW:
        return f"S5: only {S5_CARE_NOTIFICATION_TYPE} allowed in care window"
    if restrictions.phase == S5Phase.RECOVERY_ELIGIBLE:
        return "S5: user still in S5; complete recovery via handoff return-ai first"
    return "S5: notification blocked"


def handoff_return_ai_block_reason(
    restrictions: S5Restrictions,
    *,
    allow_upsell: bool,
) -> str | None:
    if not restrictions.active:
        return None
    if allow_upsell:
        return "S5: allow_upsell must be false while relationship_stage is S5"
    if not restrictions.recovery_eligible:
        return (
            f"S5: return-to-ai blocked until {RECOVERY_DAYS:.0f} days after crisis "
            "(recovery not eligible yet)"
        )
    return None


def render_s5_prompt_supplement(phase: S5Phase | None) -> str:
    phase_note = {
        S5Phase.ACUTE: "当前处于危机后 0–48h：只共情与安全感，禁止任何推销。",
        S5Phase.CARE_WINDOW: "当前处于 48–72h 关怀窗：可温和关心，禁止推销与付费引导。",
        S5Phase.STABILIZATION: "危机后 72h–7d：仍禁止 Upsell / VIP / 付费引导。",
        S5Phase.RECOVERY_ELIGIBLE: "已满 7 天：可由运营评估恢复；仍禁止主动推销直至阶段下调。",
    }.get(phase or S5Phase.ACUTE, "")
    return (
        "【S5 危机恢复限制】\n"
        f"{phase_note}\n"
        "- 禁止：订阅/VIP/付费/打赏/升级/限时优惠/任何商业转化话术。\n"
        "- 禁止：暧昧升级、性暗示、依赖强化式营销。\n"
        "- 允许：倾听、情绪支持、安全资源、运营已接管说明。"
    )
