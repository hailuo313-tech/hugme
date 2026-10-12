from __future__ import annotations

import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "db" / "migration" / "V6__seed_script_templates.sql"


def test_scripts_seed_has_at_least_ten_templates_per_category() -> None:
    text = SEED.read_text(encoding="utf-8")
    categories = re.findall(r"\('([^']+)','[^']+'", text)
    counts = Counter(categories)

    for category in ("greeting", "conversion", "refusal", "probe", "fallback"):
        assert counts[category] >= 10


def test_scripts_seed_adds_retrieval_columns_and_indexes() -> None:
    text = SEED.read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS platform" in text
    assert "ADD COLUMN IF NOT EXISTS embedding vector(1536)" in text
    assert "idx_script_templates_filter_contract" in text
    assert "idx_script_templates_embedding_ivfflat" in text
