from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.admin import require_operator
from api.ai_ops_admin import router
import api.ai_ops_admin as ai_ops_admin
from services.intent_keyword_engine import IntentKeywordEngine
from services.safety_filter import SafetyFilter


ROOT = Path(__file__).resolve().parents[1]


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/ai-ops/admin")
    app.dependency_overrides[require_operator] = lambda: {"operator_id": "test"}
    return TestClient(app)


def test_ai_ops_page_exposes_editable_management_sections() -> None:
    page = (ROOT / "admin/app/ai-ops/page.tsx").read_text(encoding="utf-8")

    for needle in [
        "话术底料审核",
        "AI 人设",
        "禁用词",
        "意图 taxonomy",
        "/ai-ops/admin/script-templates",
        "/ai-ops/admin/persona-prompts",
        "/ai-ops/admin/redlines",
        "/ai-ops/admin/intent-rules",
        "新增",
        "编辑",
        "删除",
        "启用",
        "停用",
    ]:
        assert needle in page


def test_intent_rule_api_edits_json_and_disabled_rules_do_not_match(
    tmp_path: Path, monkeypatch,
) -> None:
    rules_path = tmp_path / "intent_keyword_rules.json"
    rules_path.write_text(
        json.dumps({"version": 1, "confidence_floor": 0.6, "rules": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(ai_ops_admin, "INTENT_RULES_PATH", rules_path)
    client = _client()

    created = client.post(
        "/api/v1/ai-ops/admin/intent-rules",
        json={
            "id": "test.intent",
            "intent": "smalltalk.greeting",
            "priority": 90,
            "confidence": 0.9,
            "keywords": ["hello-test"],
            "patterns": [],
            "enabled": False,
        },
    )
    assert created.status_code == 201, created.text

    engine = IntentKeywordEngine(rules_path)
    assert engine.match("hello-test") == []

    updated = client.patch(
        "/api/v1/ai-ops/admin/intent-rules/test.intent",
        json={
            "id": "test.intent",
            "intent": "smalltalk.greeting",
            "priority": 90,
            "confidence": 0.9,
            "keywords": ["hello-test"],
            "patterns": [],
            "enabled": True,
        },
    )
    assert updated.status_code == 200, updated.text
    assert engine.match("hello-test")[0].intent == "smalltalk.greeting"

    deleted = client.delete("/api/v1/ai-ops/admin/intent-rules/test.intent")
    assert deleted.status_code == 200, deleted.text
    assert json.loads(rules_path.read_text(encoding="utf-8"))["rules"] == []


def test_redline_api_edits_json_and_disabled_rules_do_not_block(
    tmp_path: Path, monkeypatch,
) -> None:
    redlines_path = tmp_path / "safety_filter_redlines.json"
    redlines_path.write_text(
        json.dumps({"version": 1, "redlines": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(ai_ops_admin, "SAFETY_REDLINES_PATH", redlines_path)
    client = _client()

    created = client.post(
        "/api/v1/ai-ops/admin/redlines",
        json={
            "id": "test_redline",
            "category": "test",
            "reason": "redline:test",
            "patterns": ["blocked-test"],
            "enabled": False,
        },
    )
    assert created.status_code == 201, created.text

    safety = SafetyFilter(redlines_path)
    assert not safety._evaluate_redlines("blocked-test").blocked

    updated = client.patch(
        "/api/v1/ai-ops/admin/redlines/test_redline",
        json={
            "id": "test_redline",
            "category": "test",
            "reason": "redline:test",
            "patterns": ["blocked-test"],
            "enabled": True,
        },
    )
    assert updated.status_code == 200, updated.text
    assert safety._evaluate_redlines("blocked-test").blocked
