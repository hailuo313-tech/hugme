"""User level grading engine (P2-05 / C-05).

Pure function ``calc_user_level`` — no DB/Redis side effects.
Thresholds externalized in ``config/level_thresholds.json`` (P2-06).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Level = Literal["S", "A", "B", "C", "D"]
ChatRoute = Literal["manual_premium", "ai_assisted", "ai_auto"]
CountryTier = Literal["T1", "T2", "T3", "unknown"]

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_T1_PATH = _REPO_ROOT / "config" / "t1_countries.json"
DEFAULT_THRESHOLDS_PATH = _REPO_ROOT / "config" / "level_thresholds.json"

# T2 sample — H-02 will replace with signed config
_DEFAULT_T2 = frozenset({"BR", "MX", "IN", "ID", "TH", "VN", "PH", "MY"})


@dataclass(frozen=True)
class LevelThresholds:
    s_min_spend: float
    a_min_spend: float
    b_min_spend: float
    vip_level_a_min: int
    tier_default_level: dict[str, Level]


@dataclass(frozen=True)
class UserLevelInput:
    profile_complete: bool
    country_code: str | None = None
    lifetime_spend_usd: float = 0.0
    vip_level: int = 0
    operator_assigned_s: bool = False


@dataclass(frozen=True)
class UserLevelResult:
    level: Level
    chat_route: ChatRoute
    reason: str
    country_tier: CountryTier


def load_json_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_t1_countries(path: Path = DEFAULT_T1_PATH) -> frozenset[str]:
    data = load_json_config(path)
    codes = {str(c).upper() for c in data.get("countries", [])}
    return frozenset(codes)


def load_thresholds(path: Path = DEFAULT_THRESHOLDS_PATH) -> LevelThresholds:
    data = load_json_config(path)
    spend = data.get("spend_usd", {})
    tier_map = data.get("tier_default_level", {})
    return LevelThresholds(
        s_min_spend=float(spend.get("s_min", 500)),
        a_min_spend=float(spend.get("a_min", 99)),
        b_min_spend=float(spend.get("b_min", 0)),
        vip_level_a_min=int(data.get("vip_level_a_min", 1)),
        tier_default_level={
            str(k): _coerce_level(str(v)) for k, v in tier_map.items()
        },
    )


def _coerce_level(value: str) -> Level:
    v = value.upper()
    if v not in {"S", "A", "B", "C", "D"}:
        raise ValueError(f"invalid level: {value}")
    return v  # type: ignore[return-value]


def country_tier(
    country_code: str | None,
    *,
    t1: frozenset[str] | None = None,
    t2: frozenset[str] | None = None,
) -> CountryTier:
    if not country_code or not str(country_code).strip():
        return "unknown"
    cc = str(country_code).strip().upper()
    t1_set = t1 if t1 is not None else load_t1_countries()
    t2_set = t2 if t2 is not None else _DEFAULT_T2
    if cc in t1_set:
        return "T1"
    if cc in t2_set:
        return "T2"
    return "T3"


def level_to_chat_route(level: Level) -> ChatRoute:
    if level in ("S", "A"):
        return "manual_premium"
    if level == "B":
        return "ai_assisted"
    return "ai_auto"


def calc_user_level(
    inp: UserLevelInput,
    thresholds: LevelThresholds | None = None,
    *,
    t1: frozenset[str] | None = None,
    t2: frozenset[str] | None = None,
) -> UserLevelResult:
    """Compute S/A/B/C/D and chat_route from profile + geo + spend."""
    th = thresholds or load_thresholds()
    tier = country_tier(inp.country_code, t1=t1, t2=t2)

    if not inp.profile_complete:
        return UserLevelResult(
            level="D",
            chat_route=level_to_chat_route("D"),
            reason="profile_incomplete_probe",
            country_tier=tier,
        )

    if inp.operator_assigned_s:
        return UserLevelResult(
            level="S",
            chat_route=level_to_chat_route("S"),
            reason="operator_assigned_s",
            country_tier=tier,
        )

    spend = max(0.0, float(inp.lifetime_spend_usd))
    if spend >= th.s_min_spend and tier == "T1":
        return UserLevelResult(
            level="S",
            chat_route=level_to_chat_route("S"),
            reason="t1_high_spend",
            country_tier=tier,
        )

    if spend >= th.a_min_spend or inp.vip_level >= th.vip_level_a_min:
        return UserLevelResult(
            level="A",
            chat_route=level_to_chat_route("A"),
            reason="spend_or_vip_a",
            country_tier=tier,
        )

    if spend >= th.b_min_spend and tier == "T1":
        return UserLevelResult(
            level="B",
            chat_route=level_to_chat_route("B"),
            reason="t1_default_b",
            country_tier=tier,
        )

    default_level = th.tier_default_level.get(tier) or th.tier_default_level.get("unknown", "C")
    return UserLevelResult(
        level=default_level,
        chat_route=level_to_chat_route(default_level),
        reason=f"tier_default_{tier.lower()}",
        country_tier=tier,
    )
