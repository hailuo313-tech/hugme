"""
D5-4: WebSocket operator task stream — delta 计算（纯函数，无 FastAPI / DB 依赖）。

``api.realtime`` 在轮询 ``handoff_tasks`` 后调用 ``diff_tasks``，决定发送
``task.upsert`` / ``task.removed``。单元测试只 import 本模块，避免拉起
``api.realtime``（会 import fastapi、sqlalchemy 等完整运行时栈）。
"""
from __future__ import annotations

from typing import Any

# 参与「是否有变化」判定的字段；其它字段变化不触发 upsert（减少噪音）。
TRACKED_FIELDS: tuple[str, ...] = (
    "status",
    "assigned_operator_id",
    "priority",
    "last_message_at",
)


def task_signature(task: dict[str, Any]) -> tuple[Any, ...]:
    """用于判断「是否发生需要推送的变化」的指纹。"""
    return tuple(task.get(f) for f in TRACKED_FIELDS)


def diff_tasks(
    prev: dict[str, dict[str, Any]],
    curr: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """计算需要推送的增/改 (upserts) 与移除 (removed_ids)。

    Args:
        prev: 上一轮的 task_id → task 映射。
        curr: 本轮 fetch 出来的 task 列表。
    Returns:
        (upserts, removed_ids)
        - upserts：新增或被跟踪字段变化的任务（保留 curr 顺序）。
        - removed_ids：上一轮存在、本轮不存在的 task_id 列表。
    """
    upserts: list[dict[str, Any]] = []
    curr_ids: set[str] = set()
    for task in curr:
        tid = task["task_id"]
        curr_ids.add(tid)
        old = prev.get(tid)
        if old is None or task_signature(old) != task_signature(task):
            upserts.append(task)
    removed_ids = [tid for tid in prev.keys() if tid not in curr_ids]
    return upserts, removed_ids
