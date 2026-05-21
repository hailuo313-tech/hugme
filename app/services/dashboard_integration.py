"""J-03 / C-10: Operator dashboard integration contract (3s takeover SLA)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

# P4-04 / C-10: operator sees urgent row and completes lock within 3s (product SLA)
TAKEOVER_SLA_MS = 3000
# WS poll interval + one round trip budget for task visibility
TASK_VISIBILITY_BUDGET_MS = 2000

LEVEL_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}

STATE_PRIORITY = {
    "WAITING_OPERATOR": 0,
    "HUMAN_LOCKED": 1,
    "AI_ACTIVE": 2,
    "CLOSED": 3,
}

ADMIN_API_PATHS = (
    "GET /api/v1/admin/conversations",
    "GET /api/v1/admin/conversations/{conversation_id}",
    "POST /api/v1/ops-ai/conversations/{conversation_id}/assist",
    "POST /api/v1/ops-ai/translate",
)

HANDOFF_API_PATHS = (
    "POST /api/v1/handoff/{task_id}/lock",
    "POST /api/v1/handoff/{task_id}/reply",
    "POST /api/v1/handoff/{task_id}/return-ai",
)

WS_OPERATOR_TASKS_PATH = "/ws/operators/tasks"

DASHBOARD_CHECKLIST_IDS = (
    "J03-01",  # admin login + JWT
    "J03-02",  # conversation list + filters
    "J03-03",  # WAITING_OPERATOR sort priority
    "J03-04",  # detail drawer + messages
    "J03-05",  # ops-ai assist
    "J03-06",  # handoff lock API
    "J03-07",  # handoff reply API
    "J03-08",  # WS task.snapshot + upsert
    "J03-09",  # 3s takeover path (lock within SLA)
    "J03-10",  # screen recording archived
)


def _state_rank(state: str | None) -> int:
    return STATE_PRIORITY.get((state or "").upper(), 99)


def _level_rank(row: dict[str, Any]) -> int:
    """Prefer explicit user_level; fallback vip_level proxy (>=3 ~ A/S)."""
    level = (row.get("user_level") or "").upper()
    if level in LEVEL_ORDER:
        return LEVEL_ORDER[level]
    vip = int(row.get("vip_level") or 0)
    if vip >= 3:
        return LEVEL_ORDER["S"]
    if vip >= 2:
        return LEVEL_ORDER["A"]
    if vip >= 1:
        return LEVEL_ORDER["B"]
    return LEVEL_ORDER["C"]


def _time_desc_key(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        normalized = str(value).replace("Z", "+00:00")
        return -datetime.fromisoformat(normalized).timestamp()
    except (TypeError, ValueError):
        return 0.0


def sort_conversations_for_dashboard(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Dashboard list sort: takeover queue first, then S→A→B, then recency."""

    def key(row: dict[str, Any]) -> tuple[int, int, int, float]:
        ts = row.get("last_message_at") or row.get("created_at")
        return (
            _state_rank(row.get("state")),
            _level_rank(row),
            -int(row.get("handoff_count") or 0),
            _time_desc_key(ts),
        )

    return sorted(rows, key=key)


def sql_order_clause_for_dashboard() -> str:
    """ORDER BY fragment aligned with ``sort_conversations_for_dashboard``.
    
    P4-04: SAB 级别排序置顶 - 优先按 S→A→B→C→D 级别排序，然后按状态和时间。
    """
    return """
            ORDER BY
              CASE 
                WHEN p.vip_level >= 3 THEN 0  -- S 级
                WHEN p.vip_level >= 2 THEN 1  -- A 级
                WHEN p.vip_level >= 1 THEN 2  -- B 级
                ELSE 3                        -- C/D 级
              END,
              CASE c.state
                WHEN 'WAITING_OPERATOR' THEN 0
                WHEN 'HUMAN_LOCKED' THEN 1
                WHEN 'AI_ACTIVE' THEN 2
                ELSE 3
              END,
              c.handoff_count DESC,
              COALESCE(c.last_message_at, c.created_at) DESC
    """


def integration_contract() -> dict[str, Any]:
    return {
        "takeover_sla_ms": TAKEOVER_SLA_MS,
        "task_visibility_budget_ms": TASK_VISIBILITY_BUDGET_MS,
        "admin_api_paths": list(ADMIN_API_PATHS),
        "handoff_api_paths": list(HANDOFF_API_PATHS),
        "ws_path": WS_OPERATOR_TASKS_PATH,
        "checklist_ids": list(DASHBOARD_CHECKLIST_IDS),
    }
