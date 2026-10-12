"""C-07: eight script_match hooks must have contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.script_match_hooks import (
    SCRIPT_HOOKS,
    ScriptMatchContext,
    evaluate_script_hook,
    hook_coverage_contract,
    validate_hook,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "c07_script_hooks.json"


def _hook_fixtures() -> list[dict]:
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    return list(data["hooks"])


@pytest.mark.parametrize("row", _hook_fixtures(), ids=[r["test_id"] for r in _hook_fixtures()])
def test_script_hook_contract(row: dict):
    hook = validate_hook(row["hook"])
    ctx = ScriptMatchContext(
        hook=hook,
        platform=row.get("platform", "telegram"),
        user_level=row.get("user_level", "C"),
        intent_id=row.get("intent_id"),
        user_text="smoke",
        script_match_stage=hook,
    )
    result = evaluate_script_hook(ctx)
    assert result.hook == hook
    assert isinstance(result.script_ids, list)
    assert result.degradation is not None
    meta = hook_coverage_contract(hook)
    assert meta["contract"] == "evaluate_script_hook"


def test_eight_hooks_registered():
    assert len(SCRIPT_HOOKS) == 8
