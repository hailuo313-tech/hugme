from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FLYWAY_INIT = ROOT / "db" / "migration" / "V1__init.sql"
DOCKER_INIT = ROOT / "scripts" / "init.sql"


def test_flyway_v1_init_exists_with_expected_name() -> None:
    assert FLYWAY_INIT.is_file()
    assert FLYWAY_INIT.name == "V1__init.sql"


def test_flyway_init_matches_existing_docker_init_schema() -> None:
    assert FLYWAY_INIT.read_text(encoding="utf-8") == DOCKER_INIT.read_text(
        encoding="utf-8"
    )


def test_flyway_init_declares_required_extensions() -> None:
    text = FLYWAY_INIT.read_text(encoding="utf-8")

    for extension in ('"uuid-ossp"', '"vector"', '"pg_trgm"'):
        assert f"CREATE EXTENSION IF NOT EXISTS {extension};" in text


def test_flyway_init_declares_core_tables() -> None:
    text = FLYWAY_INIT.read_text(encoding="utf-8")

    for table in (
        "users",
        "user_profiles",
        "persona_prompts",
        "characters",
        "conversations",
        "messages",
        "memories",
        "handoff_tasks",
        "notification_tasks",
        "orders",
        "risk_events",
        "scripts",
        "operators",
        "stripe_webhook_events",
        "operator_quality_scores",
        "ab_experiments",
        "ab_variants",
        "ab_assignments",
        "ab_events",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in text


def test_flyway_init_contains_seed_and_indexes() -> None:
    text = FLYWAY_INIT.read_text(encoding="utf-8")

    assert "INSERT INTO persona_prompts" in text
    assert "ON CONFLICT (slug) DO NOTHING" in text
    assert "idx_memories_user_active_created_at" in text
    assert "idx_stripe_webhook_events_type_received" in text
