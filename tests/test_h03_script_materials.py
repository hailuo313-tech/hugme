from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATERIALS = ROOT / "config" / "h03_approved_script_materials.json"


def test_h03_script_materials_have_approval_and_minimum_count():
    data = json.loads(MATERIALS.read_text(encoding="utf-8"))
    scripts = data["scripts"]

    assert data["task_id"] == "H-03"
    assert data["status"] == "approved"
    assert data["approval"]["minimum_count"] == 50
    assert len(scripts) >= 50
    assert all(item["review_status"] == "approved" for item in scripts)


def test_h03_script_materials_cover_required_categories():
    data = json.loads(MATERIALS.read_text(encoding="utf-8"))
    categories = {item["category"] for item in data["scripts"]}

    assert {"greeting", "conversion", "refusal"} <= categories
    assert {"probe", "retention"} <= categories


def test_h03_script_material_keys_and_content_are_ready_for_seed():
    data = json.loads(MATERIALS.read_text(encoding="utf-8"))
    scripts = data["scripts"]
    keys = [item["key"] for item in scripts]

    assert len(keys) == len(set(keys))
    for item in scripts:
        assert item["script_type"]
        assert item["risk_level"] in {"low", "medium", "high"}
        assert item["content"].strip()
        assert "系统提示" not in item["content"] or item["category"] == "refusal"
