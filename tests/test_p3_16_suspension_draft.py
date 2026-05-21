from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from services import suspension_service as svc
from services.script_template_retriever import ScriptTemplateHit


@dataclass
class _Row:
    values: tuple

    def __getitem__(self, index):
        return self.values[index]


class _Result:
    def __init__(self, rows=None):
        self.rows = rows or []

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _FakeDb:
    def __init__(self, rows):
        self.rows = list(rows)
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        if str(statement).lstrip().upper().startswith("SELECT"):
            return _Result([self.rows.pop(0)] if self.rows else [])
        return _Result()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _hit(index: int) -> ScriptTemplateHit:
    return ScriptTemplateHit(
        id=f"script-{index}",
        category_key="conversion",
        title=f"title {index}",
        content=f"content {index}",
        language="zh",
        platform="telegram_real_user",
        user_level="S",
        persona_slug=None,
        hook="operator",
        similarity=0.9 - index / 10,
    )


def test_p3_16_build_draft_content_contains_top3_scripts():
    content = svc._build_draft_content([_hit(1), _hit(2), _hit(3)])

    assert "1. title 1" in content
    assert "2. title 2" in content
    assert "3. title 3" in content
    assert "content 3" in content


@pytest.mark.asyncio
async def test_p3_16_create_handoff_draft_persists_top3_and_countdown(monkeypatch):
    async def fake_generate(**_kwargs):
        hits = [_hit(1), _hit(2), _hit(3)]
        return hits, [hit.id for hit in hits]

    monkeypatch.setattr(svc, "generate_draft_scripts", fake_generate)
    db = _FakeDb([_Row(("task-1", "user-1", "S", "telegram_real_user"))])

    result = await svc.create_handoff_draft(
        db=db,
        task_id="task-1",
        query_text="help",
        countdown_seconds=120,
        trace_id="trace-p3-16",
    )

    update_sql, update_params = db.executed[1]
    assert result["success"] is True
    assert result["script_ids"] == ["script-1", "script-2", "script-3"]
    assert "UPDATE handoff_tasks" in update_sql
    assert update_params["countdown"] == 120
    assert update_params["script_ids"] == ["script-1", "script-2", "script-3"]
    assert db.commits == 1


@pytest.mark.asyncio
async def test_p3_16_get_draft_with_countdown_reports_remaining_seconds():
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=90)
    db = _FakeDb([
        _Row(("task-1", "draft", ["script-1"], datetime.now(timezone.utc), expires_at, 120, "HUMAN_LOCKED"))
    ])

    result = await svc.get_draft_with_countdown(db, "task-1")

    assert result["success"] is True
    assert result["has_draft"] is True
    assert result["script_ids"] == ["script-1"]
    assert 0 < result["remaining_seconds"] <= 90
    assert result["is_expired"] is False
