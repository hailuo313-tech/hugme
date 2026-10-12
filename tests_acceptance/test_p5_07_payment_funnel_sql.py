from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL_PATH = ROOT / "monitoring" / "sql" / "p5_07_payment_conversion_funnel.sql"
DOC_PATH = ROOT / "docs" / "P5-07_PAYMENT_CONVERSION_FUNNEL_SQL.md"
BUSINESS_FLOW_PATH = ROOT / "docs" / "product" / "business-flow.html"


def _sql() -> str:
    return SQL_PATH.read_text(encoding="utf-8")


def test_p5_07_sql_artifact_exists_and_has_review_marker() -> None:
    text = _sql()

    assert "P5-07: Payment conversion funnel SQL" in text
    assert "Review status: SQL reviewed for P5-07 acceptance." in text
    assert text.strip().endswith(";")


def test_p5_07_funnel_has_stable_stage_contract() -> None:
    text = _sql()

    expected_stages = [
        "eligible_users",
        "conversion_script_exposed",
        "checkout_created",
        "stripe_session_created",
        "payment_succeeded",
        "vip_upgraded",
    ]
    for stage in expected_stages:
        assert f"'{stage}'" in text

    for column in (
        "stage_order",
        "stage_key",
        "users_count",
        "orders_count",
        "gross_revenue_usd",
        "conversion_from_previous",
        "conversion_from_eligible",
    ):
        assert column in text


def test_p5_07_sql_uses_payment_and_script_trace_tables() -> None:
    text = _sql()

    for table in (
        "orders",
        "users",
        "user_profiles",
        "conversation_script_hits",
        "conversations",
        "script_templates",
    ):
        assert table in text

    assert "o.status = 'paid'" in text
    assert "o.paid_at IS NOT NULL" in text
    assert "up.vip_level, 0) >= 1" in text
    assert "category_key = 'conversion'" in text


def test_p5_07_sql_is_aggregate_only_and_avoids_sensitive_fields() -> None:
    lowered = _sql().lower()

    assert "select *" not in lowered
    for forbidden in ("sender_phone", "external_id", "content ", "payload"):
        assert forbidden not in lowered


def test_p5_07_review_doc_and_business_flow_are_marked_done() -> None:
    doc = DOC_PATH.read_text(encoding="utf-8")
    assert "Approved for P5-07 SQL review baseline." in doc

    src = BUSINESS_FLOW_PATH.read_text(encoding="utf-8")
    line = next(line for line in src.splitlines() if 'id:"P5-07"' in line)
    assert "baseline:true" in line
