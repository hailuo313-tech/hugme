"""V28 migration adds play_sequence to video_broadcast_assets."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "db" / "migration" / "V28__call_broadcast_play_sequence.sql").read_text(encoding="utf-8")


def test_v28_adds_play_sequence_column() -> None:
    assert "play_sequence" in SQL
    assert "BETWEEN 1 AND 3" in SQL


def test_v28_unique_active_sequence_index() -> None:
    assert "idx_video_broadcast_assets_active_play_sequence" in SQL
