from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services import script_template_retriever as retriever
from services.script_template_retriever import ScriptTemplateQuery


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _DB:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return _Result(self.rows)


def _row(i: int, **overrides):
    data = {
        "id": f"00000000-0000-0000-0000-00000000000{i}",
        "category_key": "greeting",
        "title": f"Template {i}",
        "content": f"content {i}",
        "language": "zh",
        "platform": "telegram_real_user",
        "user_level": "C",
        "persona_slug": "aria_warm_friend",
        "hook": "reply",
        "similarity": 0.9 - i * 0.01,
    }
    data.update(overrides)
    return data


@pytest.mark.asyncio
async def test_vector_search_returns_top3_under_100ms(monkeypatch):
    monkeypatch.setattr(
        retriever,
        "embed",
        AsyncMock(return_value=SimpleNamespace(error=None, vectors=[[0.1] * 4])),
    )
    db = _DB([_row(1), _row(2), _row(3), _row(4)])

    result = await retriever.search_script_templates(
        db=db,
        query=ScriptTemplateQuery(query="hello", limit=3),
        trace_id="t-p3-03",
    )

    assert len(result.hits) == 3
    assert result.embedding_used is True
    assert result.latency_ms < 100
    sql, params = db.calls[0]
    assert "embedding <=>" in sql
    assert params["limit"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hook,platform,user_level,persona_slug,category_key",
    [
        ("inbound", "telegram_real_user", "D", "aria_warm_friend", "greeting"),
        ("consumption", "telegram_real_user", "S", "aria_warm_friend", "conversion"),
        ("probe", "telegram_real_user", "D", "sol_calm_guide", "probe"),
        ("grading", "telegram_real_user", "B", "aria_warm_friend", "fallback"),
        ("reply", "web", "C", "aria_warm_friend", "refusal"),
        ("operator", "telegram_real_user", "A", "sol_calm_guide", "conversion"),
        ("outbound", "telegram_real_user", "C", "mira_playful_muse", "fallback"),
        ("archive", "telegram_real_user", "S", "sol_calm_guide", "greeting"),
    ],
)
async def test_filter_contract_for_platform_level_persona_and_step(
    monkeypatch,
    hook,
    platform,
    user_level,
    persona_slug,
    category_key,
):
    monkeypatch.setattr(
        retriever,
        "embed",
        AsyncMock(return_value=SimpleNamespace(error="OPENAI_API_KEY_MISSING", vectors=[])),
    )
    db = _DB(
        [
            _row(
                1,
                hook=hook,
                platform=platform,
                user_level=user_level,
                persona_slug=persona_slug,
                category_key=category_key,
                similarity=None,
            )
        ]
    )

    result = await retriever.search_script_templates(
        db=db,
        query=ScriptTemplateQuery(
            query="safe copy",
            platform=platform,
            user_level=user_level,
            persona_slug=persona_slug,
            hook=hook,
            category_key=category_key,
        ),
    )

    assert result.hits[0].hook == hook
    assert result.embedding_used is False
    sql, params = db.calls[0]
    assert "(platform = :platform OR platform IS NULL)" in sql
    assert "(user_level = :user_level OR user_level IS NULL)" in sql
    assert "(persona_slug = :persona_slug OR persona_slug IS NULL)" in sql
    assert "(hook = :hook OR hook IS NULL)" in sql
    assert "category_key = :category_key" in sql
    assert params["platform"] == platform
    assert params["user_level"] == user_level
    assert params["persona_slug"] == persona_slug
    assert params["hook"] == hook
    assert params["category_key"] == category_key
