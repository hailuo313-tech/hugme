from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from services.level_engine import country_tier, load_t1_countries
from services.t1_country_config import (
    T1CountryConfigLoader,
    clear_t1_country_loader_cache,
    get_t1_country_loader,
)


def _write_config(path: Path, countries: list[str], version: int = 1) -> None:
    path.write_text(
        json.dumps(
            {
                "version": version,
                "status": "approved",
                "countries": countries,
                "approval": {"task_id": "H-02"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    os.utime(path, (1_700_000_000 + version, 1_700_000_000 + version))


def test_loader_hot_reloads_when_t1_countries_file_changes(tmp_path: Path) -> None:
    path = tmp_path / "t1_countries.json"
    _write_config(path, ["US", "SG"], version=1)
    loader = T1CountryConfigLoader(path)

    assert loader.get_countries() == frozenset({"US", "SG"})

    _write_config(path, ["BR", "JP"], version=2)
    snapshot = loader.get_snapshot()

    assert snapshot.version == 2
    assert snapshot.countries == frozenset({"BR", "JP"})


def test_level_engine_load_t1_countries_uses_hot_loader(tmp_path: Path) -> None:
    path = tmp_path / "t1_countries.json"
    _write_config(path, ["US"], version=1)
    clear_t1_country_loader_cache(path)

    assert load_t1_countries(path) == frozenset({"US"})
    assert country_tier("US", t1=load_t1_countries(path)) == "T1"

    _write_config(path, ["BR"], version=2)

    assert load_t1_countries(path) == frozenset({"BR"})
    assert country_tier("US", t1=load_t1_countries(path)) == "T3"
    assert country_tier("BR", t1=load_t1_countries(path)) == "T1"


def test_shared_loader_instance_is_cached_but_snapshot_refreshes(tmp_path: Path) -> None:
    path = tmp_path / "t1_countries.json"
    _write_config(path, ["US"], version=1)
    clear_t1_country_loader_cache(path)

    first = get_t1_country_loader(path)
    second = get_t1_country_loader(path)

    assert first is second
    assert first.get_snapshot().countries == frozenset({"US"})

    _write_config(path, ["CA"], version=2)

    assert second.get_snapshot().countries == frozenset({"CA"})


def test_invalid_country_code_fails_fast(tmp_path: Path) -> None:
    path = tmp_path / "t1_countries.json"
    _write_config(path, ["USA"], version=1)

    with pytest.raises(ValueError):
        T1CountryConfigLoader(path).get_countries()
