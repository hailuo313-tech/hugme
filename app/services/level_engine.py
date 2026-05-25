"""User level grading engine (P2-05 / C-05).

Pure function ``calc_user_level`` — no DB/Redis side effects.
Thresholds externalized in ``config/level_thresholds.json`` (P2-06).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from services.t1_country_config import load_t1_countries_hot
from services.t2_country_config import load_t2_countries_hot

Level = Literal["S", "A", "B", "C", "D"]
ChatRoute = Literal["manual_premium", "ai_assisted", "ai_auto"]
CountryTier = Literal["T1", "T2", "T3", "unknown"]

CHAT_ROUTE_BY_LEVEL: dict[Level, ChatRoute] = {
    "S": "manual_premium",
    "A": "manual_premium",
    "B": "ai_assisted",
    "C": "ai_auto",
    "D": "ai_auto",
}

_SERVICE_PATH = Path(__file__).resolve()
_REPO_ROOT = _SERVICE_PATH.parents[2]


def _config_candidates(filename: str) -> list[Path]:
    env_dir = os.environ.get("ERIS_CONFIG_DIR")
    candidates: list[Path] = []
    if env_dir:
        candidates.append(Path(env_dir) / filename)
    for root in (_REPO_ROOT, _SERVICE_PATH.parents[1], Path("/app")):
        candidates.append(root / "config" / filename)
    return candidates


def _default_config_path(filename: str) -> Path:
    candidates = _config_candidates(filename)
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def _default_env_path() -> Path:
    for root in (_REPO_ROOT, _SERVICE_PATH.parents[1], Path("/app")):
        path = root / ".env"
        if path.exists():
            return path
    return _REPO_ROOT / ".env"


DEFAULT_T1_PATH = _default_config_path("t1_countries.json")
DEFAULT_T2_PATH = _default_config_path("t2_countries.json")
DEFAULT_THRESHOLDS_PATH = _default_config_path("level_thresholds.json")
DEFAULT_ENV_PATH = _default_env_path()

# Legacy fallback if t2_countries.json is missing (tests may inject t2= explicitly).
_DEFAULT_T2_FALLBACK = frozenset({"BR", "MX", "IN", "ID", "TH", "VN", "PH", "MY"})


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
    return load_t1_countries_hot(path)


def load_t2_countries(
    path: Path = DEFAULT_T2_PATH,
    *,
    t1_path: Path | None = None,
) -> frozenset[str]:
    if not path.exists():
        return _DEFAULT_T2_FALLBACK
    t1 = load_t1_countries(t1_path or DEFAULT_T1_PATH)
    return load_t2_countries_hot(path, t1_countries=t1)


def load_thresholds(
    path: Path = DEFAULT_THRESHOLDS_PATH,
    *,
    env_path: Path = DEFAULT_ENV_PATH,
) -> LevelThresholds:
    data = load_json_config(path)
    spend = data.get("spend_usd", {})
    tier_map = data.get("tier_default_level", {})
    env = _load_env_overrides(env_path)
    return LevelThresholds(
        s_min_spend=_env_float(env, "LEVEL_S_MIN_SPEND", spend.get("s_min", 500)),
        a_min_spend=_env_float(env, "LEVEL_A_MIN_SPEND", spend.get("a_min", 99)),
        b_min_spend=_env_float(env, "LEVEL_B_MIN_SPEND", spend.get("b_min", 0)),
        vip_level_a_min=_env_int(
            env,
            "LEVEL_VIP_LEVEL_A_MIN",
            data.get("vip_level_a_min", 1),
        ),
        tier_default_level={
            "T1": _coerce_level(_env_value(env, "LEVEL_T1_DEFAULT", tier_map.get("T1", "B"))),
            "T2": _coerce_level(_env_value(env, "LEVEL_T2_DEFAULT", tier_map.get("T2", "C"))),
            "T3": _coerce_level(_env_value(env, "LEVEL_T3_DEFAULT", tier_map.get("T3", "C"))),
            "unknown": _coerce_level(
                _env_value(env, "LEVEL_UNKNOWN_DEFAULT", tier_map.get("unknown", "C"))
            ),
        },
    )


def _coerce_level(value: str) -> Level:
    v = value.upper()
    if v not in {"S", "A", "B", "C", "D"}:
        raise ValueError(f"invalid level: {value}")
    return v  # type: ignore[return-value]


def _load_env_overrides(path: Path) -> dict[str, str]:
    values = {k: v for k, v in os.environ.items() if k.startswith("LEVEL_")}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, raw_value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if key.startswith("LEVEL_") and key not in values:
            values[key] = _strip_env_value(raw_value)
    return values


def _strip_env_value(value: str) -> str:
    cleaned = value.strip()
    if "#" in cleaned and not cleaned.startswith(("'", '"')):
        cleaned = cleaned.split("#", 1)[0].strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ("'", '"'):
        return cleaned[1:-1]
    return cleaned


def _env_value(env: dict[str, str], key: str, default: object) -> str:
    value = env.get(key)
    if value is None or str(value).strip() == "":
        return str(default)
    return str(value).strip()


def _env_float(env: dict[str, str], key: str, default: object) -> float:
    return float(_env_value(env, key, default))


def _env_int(env: dict[str, str], key: str, default: object) -> int:
    return int(_env_value(env, key, default))


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
    t2_set = t2 if t2 is not None else load_t2_countries()
    if cc in t1_set:
        return "T1"
    if cc in t2_set:
        return "T2"
    return "T3"


def level_to_chat_route(level: Level) -> ChatRoute:
    return CHAT_ROUTE_BY_LEVEL[level]


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
