import json
from datetime import datetime, timezone

import pytest

from services.auto_delivery_worker import (
    DEFAULT_TIMEOUT_FALLBACK_CONTENT,
    DEFAULT_TIMEOUT_FALLBACK_SCRIPT_HIT_ID,
    TIMEOUT_FALLBACK_DELIVERY_MODE,
    TIMEOUT_FALLBACK_MESSAGE_TYPE,
    _build_timeout_fallback_metadata,
    _normalize_timeout_fallback_script,
    schedule_expired_timeout_fallbacks,
)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self):
        self.inserted = []
        self.commits = 0

    async def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}
        if "FROM handoff_tasks" in sql:
            return _Result(
                [
                    {
                        "handoff_task_id": "task-1",
                        "user_id": "user-1",
                        "conversation_id": "conv-1",
                        "external_user_id": "tg_123456789",
                        "user_level": "S",
                        "platform": "telegram_real_user",
                        "draft_expires_at": datetime.now(timezone.utc),
                    }
                ]
            )
        if "FROM script_templates" in sql:
            return _Result(
                [
                    {
                        "id": "script-timeout-1",
                        "content": "我先接住这条消息，稍后继续跟进。",
                    }
                ]
            )
        if "INSERT INTO message_schedules" in sql:
            self.inserted.append(params)
            return _Result([])
        return _Result([])

    async def commit(self):
        self.commits += 1


def test_p3_17_default_fallback_script_has_stable_script_hit_id():
    script = _normalize_timeout_fallback_script(None)

    assert script["script_hit_id"] == DEFAULT_TIMEOUT_FALLBACK_SCRIPT_HIT_ID
    assert script["content"] == DEFAULT_TIMEOUT_FALLBACK_CONTENT


def test_p3_17_timeout_metadata_contains_script_hit_id():
    metadata = _build_timeout_fallback_metadata(
        handoff_task_id="task-1",
        conversation_id="conv-1",
        user_level="S",
        script_hit_id="script-1",
        trace_id="trace-1",
    )

    assert metadata["delivery_mode"] == TIMEOUT_FALLBACK_DELIVERY_MODE
    assert metadata["fallback_reason"] == "handoff_draft_timeout_120s"
    assert metadata["script_hit_id"] == "script-1"
    assert metadata["source_handoff_task_id"] == "task-1"


@pytest.mark.asyncio
async def test_p3_17_expired_handoff_queues_timeout_fallback_with_script_hit_id():
    session = _FakeSession()

    queued = await schedule_expired_timeout_fallbacks(
        session,
        trace_id="trace-p3-17",
    )

    assert queued == 1
    assert session.commits == 1
    assert len(session.inserted) == 1

    inserted = session.inserted[0]
    metadata = json.loads(inserted["metadata"])
    assert inserted["message_type"] == TIMEOUT_FALLBACK_MESSAGE_TYPE
    assert inserted["chat_id"] == 123456789
    assert metadata["script_hit_id"] == "script-timeout-1"
    assert metadata["delivery_mode"] == TIMEOUT_FALLBACK_DELIVERY_MODE
    assert metadata["source_handoff_task_id"] == "task-1"
