"""P5-09 level-based canary feature flags."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from services.level_engine import CHAT_ROUTE_BY_LEVEL, ChatRoute, Level


@dataclass(frozen=True)
class LevelCanaryPolicy:
    task_id: str
    level_routes: dict[Level, ChatRoute]
    traffic_percent: dict[Level, int]


@dataclass(frozen=True)
class LevelCanaryDecision:
    level: Level
    chat_route: ChatRoute
    enabled: bool
    reason: str
    traffic_percent: int


def load_policy(path: Path) -> LevelCanaryPolicy:
    data = json.loads(path.read_text(encoding="utf-8"))
    task_id = str(data.get("task_id") or path.stem)
    traffic_policy = data.get("traffic_policy") or {}

    if task_id == "H-07":
        included = [_coerce_level(level) for level in traffic_policy.get("included_levels", [])]
        routes = traffic_policy.get("included_chat_routes", [])
        if routes != ["ai_auto"]:
            raise ValueError("H-07 must include only ai_auto route")
        percent = int(traffic_policy.get("eligible_traffic_percent") or 0)
        return LevelCanaryPolicy(
            task_id=task_id,
            level_routes={level: "ai_auto" for level in included},
            traffic_percent={level: percent for level in included},
        )

    level_routes = {
        _coerce_level(level): _coerce_route(route)
        for level, route in (traffic_policy.get("level_routes") or {}).items()
    }
    raw_percent = traffic_policy.get("eligible_traffic_percent") or {}
    return LevelCanaryPolicy(
        task_id=task_id,
        level_routes=level_routes,
        traffic_percent={
            _coerce_level(level): int(percent) for level, percent in raw_percent.items()
        },
    )


def decide_level_canary(
    *,
    level: Level,
    user_id: str,
    policy: LevelCanaryPolicy,
    feature_enabled: bool = True,
) -> LevelCanaryDecision:
    chat_route = CHAT_ROUTE_BY_LEVEL[level]
    if not feature_enabled:
        return LevelCanaryDecision(level, chat_route, False, "feature_disabled", 0)

    configured_route = policy.level_routes.get(level)
    if configured_route is None:
        return LevelCanaryDecision(level, chat_route, False, "level_not_enabled", 0)
    if configured_route != chat_route:
        return LevelCanaryDecision(level, chat_route, False, "route_mismatch", 0)

    percent = max(0, min(100, int(policy.traffic_percent.get(level, 0))))
    if percent <= 0:
        return LevelCanaryDecision(level, chat_route, False, "traffic_percent_zero", percent)
    if _stable_bucket(user_id) >= percent:
        return LevelCanaryDecision(level, chat_route, False, "traffic_bucket_excluded", percent)

    return LevelCanaryDecision(level, chat_route, True, "enabled", percent)


def _stable_bucket(user_id: str) -> float:
    digest = hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF * 100.0


def _coerce_level(value: str) -> Level:
    level = value.upper()
    if level not in CHAT_ROUTE_BY_LEVEL:
        raise ValueError(f"invalid level: {value}")
    return level  # type: ignore[return-value]


def _coerce_route(value: str) -> ChatRoute:
    if value not in {"manual_premium", "ai_assisted", "ai_auto"}:
        raise ValueError(f"invalid chat route: {value}")
    return value  # type: ignore[return-value]
