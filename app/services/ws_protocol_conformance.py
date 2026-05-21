"""C-09: WebSocket protocol conformance helpers (docs/ws_protocol.md)."""

from __future__ import annotations

from typing import Any

# Mirrors app/api/realtime.py + D5-4 spec
WS_PATH = "/ws/operators/tasks"
POLL_INTERVAL_MS = 1000
OPEN_TASK_STATUSES = ("pending", "PENDING", "ESCALATED", "HUMAN_LOCKED")

SERVER_EVENT_TYPES = frozenset(
    {
        "connection.ready",
        "task.snapshot",
        "task.upsert",
        "task.removed",
        "pong",
        "user.upgraded",
    }
)
CLIENT_EVENT_TYPES = frozenset({"ping", "task.ack", "message.ack"})

TASK_REQUIRED_FIELDS = frozenset(
    {
        "task_id",
        "user_id",
        "conversation_id",
        "priority",
        "trigger_reason",
        "status",
        "assigned_operator_id",
        "locked_at",
        "closed_at",
        "created_at",
        "last_message_at",
        "channel",
        "external_id",
        "risk_level",
    }
)

TRACKED_DELTA_FIELDS = frozenset(
    {"status", "assigned_operator_id", "priority", "last_message_at"}
)


def validate_task(task: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(task, dict):
        return ["task must be object"]
    missing = TASK_REQUIRED_FIELDS - set(task.keys())
    if missing:
        errors.append(f"task missing fields: {sorted(missing)}")
    return errors


def validate_server_event(msg: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(msg, dict):
        return ["message must be object"]
    t = msg.get("type")
    if t not in SERVER_EVENT_TYPES:
        errors.append(f"unknown server type: {t}")
        return errors
    if "trace_id" not in msg:
        errors.append("missing trace_id")

    if t == "connection.ready":
        for k in ("operator_id", "poll_interval_ms"):
            if k not in msg:
                errors.append(f"connection.ready missing {k}")
        if msg.get("poll_interval_ms") != POLL_INTERVAL_MS:
            errors.append(f"poll_interval_ms expected {POLL_INTERVAL_MS}")

    elif t == "task.snapshot":
        tasks = msg.get("tasks")
        if not isinstance(tasks, list):
            errors.append("task.snapshot.tasks must be list")
        else:
            for i, task in enumerate(tasks):
                errors.extend(f"tasks[{i}]: {e}" for e in validate_task(task))

    elif t == "task.upsert":
        task = msg.get("task")
        if not isinstance(task, dict):
            errors.append("task.upsert.task must be object")
        else:
            errors.extend(validate_task(task))

    elif t == "task.removed":
        if not msg.get("task_id"):
            errors.append("task.removed missing task_id")

    elif t == "user.upgraded":
        for k in ("user_id", "previous_level", "new_level", "reason", "upgraded_at"):
            if k not in msg:
                errors.append(f"user.upgraded missing {k}")

    return errors


def validate_client_event(msg: dict[str, Any]) -> list[str]:
    if not isinstance(msg, dict):
        return ["message must be object"]
    t = msg.get("type")
    if t not in CLIENT_EVENT_TYPES:
        return [f"unknown client type: {t}"]
    if t == "task.ack" and not msg.get("task_id"):
        return ["task.ack missing task_id"]
    if t == "message.ack" and not msg.get("message_id"):
        return ["message.ack missing message_id"]
    return []


def implementation_contract() -> dict[str, Any]:
    """Snapshot of runtime constants for C-09 audit."""
    from services.ws_operator_task_delta import TRACKED_FIELDS

    return {
        "ws_path": WS_PATH,
        "poll_interval_ms": POLL_INTERVAL_MS,
        "open_task_statuses": list(OPEN_TASK_STATUSES),
        "server_event_types": sorted(SERVER_EVENT_TYPES),
        "client_event_types": sorted(CLIENT_EVENT_TYPES),
        "task_required_fields": sorted(TASK_REQUIRED_FIELDS),
        "tracked_delta_fields": list(TRACKED_FIELDS),
    }
