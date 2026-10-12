from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from services.level_engine import country_tier, load_t2_countries
from services.t2_country_config import (
    T2CountryConfigLoader,
    clear_t2_country_loader_cache,
    get_t2_country_loader,
)


def _write_config(path: Path, countries: list[str], version: int = 1) -> None:
    path.write_text(
        json.dumps(
            {
                "version": version,
                "status": "approved",
                "countries": countries,
                "entries": [
                    {
                        "code": code,
                        "name_zh": code,
                        "region": "test",
                        "dial_code": "+0",
                        "ops_note": "test",
                    }
                    for code in countries
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    os.utime(path, (1_700_000_000 + version, 1_700_000_000 + version))


def test_loader_hot_reloads_when_t2_countries_file_changes(tmp_path: Path) -> None:
    path = tmp_path / "t2_countries.json"
    _write_config(path, ["TW", "MY"], version=1)
    loader = T2CountryConfigLoader(path)

    assert loader.get_countries() == frozenset({"TW", "MY"})

    _write_config(path, ["BR", "MX"], version=2)
    snapshot = loader.get_snapshot()

    assert snapshot.version == 2
    assert snapshot.countries == frozenset({"BR", "MX"})


def test_level_engine_load_t2_countries_uses_hot_loader(tmp_path: Path) -> None:
    t1_path = tmp_path / "t1_countries.json"
    t2_path = tmp_path / "t2_countries.json"
    t1_path.write_text(
        json.dumps({"version": 1, "countries": ["US"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_config(t2_path, ["TW", "US"], version=1)
    clear_t2_country_loader_cache(t2_path)

    with pytest.raises(ValueError, match="overlaps t1"):
        load_t2_countries(t2_path, t1_path=t1_path)

    _write_config(t2_path, ["TW", "BR"], version=2)
    clear_t2_country_loader_cache(t2_path)

    assert load_t2_countries(t2_path, t1_path=t1_path) == frozenset({"TW", "BR"})
    assert country_tier("TW", t1={"US"}, t2=load_t2_countries(t2_path, t1_path=t1_path)) == "T2"
    assert country_tier("CN", t1={"US"}, t2=load_t2_countries(t2_path, t1_path=t1_path)) == "T3"


def test_signed_t2_config_excludes_t1_overlap() -> None:
    from services.level_engine import load_t1_countries

    t1 = load_t1_countries()
    t2 = load_t2_countries()
    assert not (t1 & t2)
    assert "HK" in t1
    assert "HK" not in t2
    assert "TW" in t2
    assert len(t2) == 48
