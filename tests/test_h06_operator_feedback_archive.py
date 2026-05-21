from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_PATH = ROOT / "config" / "h06_operator_feedback_archive.json"


def _load_archive() -> dict:
    return json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))


def test_h06_feedback_archive_is_approved() -> None:
    archive = _load_archive()

    assert archive["task_id"] == "H-06"
    assert archive["status"] == "approved"
    assert archive["approved_on"] == "2026-05-20"
    assert archive["approved_by"] == "ops_owner"
    assert "pending_final_review" not in archive["approved_by"]


def test_h06_has_at_least_five_processed_feedback_items() -> None:
    archive = _load_archive()
    items = archive["processed_feedback"]
    acceptance = archive["acceptance"]

    assert acceptance["required_processed_feedback_count"] == 5
    assert acceptance["actual_processed_feedback_count"] == len(items) >= 5
    assert {item["status"] for item in items} == {"processed"}
    assert all(item["processed_on"] for item in items)
    assert all("pending_final_review" not in item["processed_by"] for item in items)


def test_h06_feedback_archive_links_dashboard_sources() -> None:
    refs = set(_load_archive()["source_refs"])

    assert "docs/H06_OPERATOR_FEEDBACK_ARCHIVE.md" in refs
    assert "app/api/feedback.py" in refs
    assert "docs/C10_INSPECTION_REPORT.md" in refs
    assert "docs/C11_INSPECTION_REPORT.md" in refs
