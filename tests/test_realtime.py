"""D5-4 单元测试：``services.ws_operator_task_delta.diff_tasks``

纯函数、无 FastAPI；与 ``app/api/realtime.py`` 中的轮询推送语义一致。
WebSocket 路由本体留给手动 smoke（需 DB + fastapi 全栈）。
"""

from __future__ import annotations

from typing import Any

from services.ws_operator_task_delta import diff_tasks


def _task(
    task_id: str,
    status: str = "pending",
    assigned_operator_id: str | None = None,
    priority: str = "P2",
    last_message_at: str | None = "2026-05-12T04:00:00",
    trigger_reason: str = "keyword_risk",
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "user_id": "u-" + task_id,
        "conversation_id": "c-" + task_id,
        "priority": priority,
        "trigger_reason": trigger_reason,
        "status": status,
        "assigned_operator_id": assigned_operator_id,
        "locked_at": None,
        "closed_at": None,
        "created_at": "2026-05-12T04:00:00",
        "last_message_at": last_message_at,
        "channel": "telegram",
        "external_id": "tg_" + task_id,
        "risk_level": "normal",
    }


def test_initial_load_all_become_upserts():
    prev: dict[str, dict[str, Any]] = {}
    curr = [_task("a"), _task("b")]
    upserts, removed = diff_tasks(prev, curr)
    assert [t["task_id"] for t in upserts] == ["a", "b"]
    assert removed == []


def test_status_change_emits_upsert():
    prev = {"a": _task("a", status="pending")}
    curr = [_task("a", status="HUMAN_LOCKED")]
    upserts, removed = diff_tasks(prev, curr)
    assert [t["task_id"] for t in upserts] == ["a"]
    assert upserts[0]["status"] == "HUMAN_LOCKED"
    assert removed == []


def test_assignee_change_emits_upsert():
    prev = {"a": _task("a", assigned_operator_id=None)}
    curr = [_task("a", assigned_operator_id="op-1")]
    upserts, removed = diff_tasks(prev, curr)
    assert [t["task_id"] for t in upserts] == ["a"]
    assert upserts[0]["assigned_operator_id"] == "op-1"


def test_no_change_emits_nothing():
    prev = {"a": _task("a")}
    curr = [_task("a")]
    upserts, removed = diff_tasks(prev, curr)
    assert upserts == []
    assert removed == []


def test_removed_when_task_disappears():
    prev = {"a": _task("a"), "b": _task("b")}
    curr = [_task("a")]
    upserts, removed = diff_tasks(prev, curr)
    assert upserts == []
    assert removed == ["b"]


def test_mixed_add_change_remove():
    prev = {
        "a": _task("a", status="pending"),
        "b": _task("b"),
    }
    curr = [
        _task("c"),
        _task("a", status="HUMAN_LOCKED"),
    ]
    upserts, removed = diff_tasks(prev, curr)
    assert [t["task_id"] for t in upserts] == ["c", "a"]
    assert removed == ["b"]


def test_non_tracked_field_change_skips_upsert():
    """trigger_reason 不在 TRACKED_FIELDS 内，变化不触发 upsert。"""
    prev = {"a": _task("a", trigger_reason="keyword_risk")}
    curr = [_task("a", trigger_reason="negative_sentiment")]
    upserts, removed = diff_tasks(prev, curr)
    assert upserts == []
    assert removed == []


def test_priority_change_emits_upsert():
    prev = {"a": _task("a", priority="P2")}
    curr = [_task("a", priority="P0")]
    upserts, removed = diff_tasks(prev, curr)
    assert [t["task_id"] for t in upserts] == ["a"]
    assert upserts[0]["priority"] == "P0"


def test_last_message_at_change_emits_upsert():
    prev = {"a": _task("a", last_message_at="2026-05-12T04:00:00")}
    curr = [_task("a", last_message_at="2026-05-12T04:01:00")]
    upserts, removed = diff_tasks(prev, curr)
    assert [t["task_id"] for t in upserts] == ["a"]
