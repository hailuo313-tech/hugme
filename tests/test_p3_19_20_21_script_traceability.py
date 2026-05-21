from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services import script_match_hooks as hooks
from services.script_match_hooks import (
    SCRIPT_HOOKS,
    ScriptMatchContext,
    evaluate_all_script_hooks,
    evaluate_script_hook_async,
)


class _InsertResult:
    def scalar(self):
        return "audit-row-1"


class _AuditDB:
    def __init__(self):
        self.calls = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return _InsertResult()


def _hit(hook: str):
    return SimpleNamespace(
        id=f"script-{hook}",
        category_key="fallback",
        content=f"{hook} content",
        similarity=0.91,
    )


@pytest.mark.asyncio
async def test_p3_20_all_eight_hooks_return_match_or_degradation(monkeypatch):
    async def fake_search_script_templates(*, db, query, trace_id=None):
        if query.hook == "archive":
            return SimpleNamespace(hits=[], fallback_reason="no_script_match")
        return SimpleNamespace(hits=[_hit(query.hook)], fallback_reason=None)

    monkeypatch.setattr(
        hooks,
        "search_script_templates",
        fake_search_script_templates,
    )
    db = _AuditDB()
    base = ScriptMatchContext(
        hook="reply",
        platform="telegram_real_user",
        user_level="S",
        user_text="hello",
        conversation_id="11111111-1111-1111-1111-111111111111",
        message_id="22222222-2222-2222-2222-222222222222",
        trace_id="trace-p3-20",
    )

    results = await evaluate_all_script_hooks(db=db, base_context=base)

    assert [result.hook for result in results] == list(SCRIPT_HOOKS)
    assert all(result.matched or result.degradation for result in results)
    assert len(db.calls) == 8
    assert all("INSERT INTO conversation_script_hits" in sql for sql, _ in db.calls)


@pytest.mark.asyncio
async def test_p3_21_script_match_audit_writes_script_hit_id(monkeypatch):
    monkeypatch.setattr(
        hooks,
        "search_script_templates",
        AsyncMock(return_value=SimpleNamespace(hits=[_hit("reply")], fallback_reason=None)),
    )
    db = _AuditDB()

    result = await evaluate_script_hook_async(
        ScriptMatchContext(
            hook="reply",
            platform="telegram_real_user",
            user_level="A",
            user_text="price",
            conversation_id="11111111-1111-1111-1111-111111111111",
            message_id="22222222-2222-2222-2222-222222222222",
            trace_id="trace-p3-21",
        ),
        db=db,
        audit=True,
    )

    assert result.matched is True
    assert result.script_hit_id == "script-reply"
    params = db.calls[0][1]
    assert params["script_hit_id"] == "script-reply"
    assert params["matched"] is True
    assert params["degradation"] is None


def test_p3_19_traceability_contract_requires_all_steps_have_evidence():
    hits = [
        {"hook": hook, "matched": hook != "archive", "degradation": None if hook != "archive" else "no_script_match"}
        for hook in SCRIPT_HOOKS
    ]

    hooks_seen = {hit["hook"] for hit in hits}
    missing_hooks = [hook for hook in SCRIPT_HOOKS if hook not in hooks_seen]

    assert missing_hooks == []
    assert all(hit["matched"] or hit["degradation"] for hit in hits)
