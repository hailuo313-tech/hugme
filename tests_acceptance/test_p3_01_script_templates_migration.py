from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEVEL_ROUTE_SQL = ROOT / "db" / "migration" / "V4__level_chat_route.sql"
SCRIPT_TEMPLATES_SQL = ROOT / "db" / "migration" / "V5__create_script_templates.sql"


def test_p2_09_level_route_migration_adds_chat_route_contract() -> None:
    text = LEVEL_ROUTE_SQL.read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS user_level" in text
    assert "ADD COLUMN IF NOT EXISTS chat_route" in text
    assert "manual_premium" in text
    assert "ai_assisted" in text
    assert "ai_auto" in text
    assert "idx_user_profiles_level_route" in text


def test_p3_01_script_templates_tables_and_five_categories() -> None:
    text = SCRIPT_TEMPLATES_SQL.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS script_template_categories" in text
    assert "CREATE TABLE IF NOT EXISTS script_templates" in text
    for category in ("greeting", "conversion", "refusal", "probe", "fallback"):
        assert f"'{category}'" in text
    assert "REFERENCES script_template_categories(key)" in text
    assert "idx_script_templates_category_status" in text
