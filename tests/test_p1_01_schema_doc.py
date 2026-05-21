from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_p1_01_db_schema_doc_exists_and_names_required_tables():
    doc = ROOT / "docs" / "db_schema_doc.md"
    text = doc.read_text(encoding="utf-8")

    assert "user_profiles" in text
    assert "premium_chat_logs" in text
    assert "audit_logs" in text
    assert "P1-01" in text


def test_p1_01_migration_creates_premium_and_audit_tables():
    migration = ROOT / "db" / "migration" / "V8__p1_premium_chat_and_audit_logs.sql"
    sql = migration.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS premium_chat_logs" in sql
    assert "CREATE TABLE IF NOT EXISTS audit_logs" in sql
    assert "idx_premium_chat_logs_user_created" in sql
    assert "idx_audit_logs_created_at" in sql
    assert "sender_phone" in sql
