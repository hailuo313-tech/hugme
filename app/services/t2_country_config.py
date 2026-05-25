"""Hot-reloadable T2 country configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any


@dataclass(frozen=True)
class T2CountryEntry:
    code: str
    name_zh: str
    region: str
    dial_code: str
    ops_note: str


@dataclass(frozen=True)
class T2CountryConfigSnapshot:
    path: Path
    mtime_ns: int
    version: int | None
    status: str | None
    countries: frozenset[str]
    entries: tuple[T2CountryEntry, ...]


class T2CountryConfigLoader:
    """Load t2_countries.json and refresh when the file changes."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()
        self._snapshot: T2CountryConfigSnapshot | None = None

    def get_snapshot(self) -> T2CountryConfigSnapshot:
        stat = self.path.stat()
        with self._lock:
            if self._snapshot is not None and self._snapshot.mtime_ns == stat.st_mtime_ns:
                return self._snapshot
            snapshot = self._load(stat.st_mtime_ns)
            self._snapshot = snapshot
            return snapshot

    def get_countries(self) -> frozenset[str]:
        return self.get_snapshot().countries

    def get_entries(self) -> tuple[T2CountryEntry, ...]:
        return self.get_snapshot().entries

    def clear_cache(self) -> None:
        with self._lock:
            self._snapshot = None

    def _load(self, mtime_ns: int) -> T2CountryConfigSnapshot:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        countries, entries = _parse_t2_config(data)
        return T2CountryConfigSnapshot(
            path=self.path,
            mtime_ns=mtime_ns,
            version=_optional_int(data.get("version")),
            status=str(data.get("status")) if data.get("status") is not None else None,
            countries=frozenset(countries),
            entries=entries,
        )


_LOADERS: dict[Path, T2CountryConfigLoader] = {}
_LOADERS_LOCK = RLock()


def get_t2_country_loader(path: Path) -> T2CountryConfigLoader:
    resolved = path.resolve()
    with _LOADERS_LOCK:
        loader = _LOADERS.get(resolved)
        if loader is None:
            loader = T2CountryConfigLoader(resolved)
            _LOADERS[resolved] = loader
        return loader


def load_t2_countries_hot(path: Path, *, t1_countries: frozenset[str] | None = None) -> frozenset[str]:
    codes = get_t2_country_loader(path).get_countries()
    if t1_countries:
        overlap = codes & t1_countries
        if overlap:
            raise ValueError(
                f"t2_countries.json overlaps t1_countries.json: {sorted(overlap)}"
            )
    return codes


def clear_t2_country_loader_cache(path: Path | None = None) -> None:
    with _LOADERS_LOCK:
        if path is None:
            for loader in _LOADERS.values():
                loader.clear_cache()
            _LOADERS.clear()
            return
        loader = _LOADERS.get(path.resolve())
        if loader is not None:
            loader.clear_cache()


def _parse_t2_config(data: dict[str, Any]) -> tuple[set[str], tuple[T2CountryEntry, ...]]:
    entries_raw = data.get("entries")
    entries: list[T2CountryEntry] = []
    codes: set[str] = set()

    if isinstance(entries_raw, list) and entries_raw:
        for item in entries_raw:
            if not isinstance(item, dict):
                raise ValueError("t2_countries.json entries must be objects")
            code = str(item.get("code", "")).strip().upper()
            if len(code) != 2 or not code.isalpha():
                raise ValueError(f"invalid ISO-3166 alpha-2 country code: {item.get('code')}")
            codes.add(code)
            entries.append(
                T2CountryEntry(
                    code=code,
                    name_zh=str(item.get("name_zh", "")).strip(),
                    region=str(item.get("region", "")).strip(),
                    dial_code=str(item.get("dial_code", "")).strip(),
                    ops_note=str(item.get("ops_note", "")).strip(),
                )
            )
    else:
        raw = data.get("countries")
        if not isinstance(raw, list):
            raise ValueError("t2_countries.json must contain countries list or entries")
        for item in raw:
            code = str(item).strip().upper()
            if len(code) != 2 or not code.isalpha():
                raise ValueError(f"invalid ISO-3166 alpha-2 country code: {item}")
            codes.add(code)

    if not codes:
        raise ValueError("t2_countries.json must contain at least one country")

    return codes, tuple(sorted(entries, key=lambda e: e.code))


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
