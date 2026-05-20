"""Hot-reloadable T1 country configuration (P2-01)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any


@dataclass(frozen=True)
class T1CountryConfigSnapshot:
    path: Path
    mtime_ns: int
    version: int | None
    status: str | None
    countries: frozenset[str]


class T1CountryConfigLoader:
    """Load t1_countries.json and refresh when the file changes."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()
        self._snapshot: T1CountryConfigSnapshot | None = None

    def get_snapshot(self) -> T1CountryConfigSnapshot:
        stat = self.path.stat()
        with self._lock:
            if self._snapshot is not None and self._snapshot.mtime_ns == stat.st_mtime_ns:
                return self._snapshot
            snapshot = self._load(stat.st_mtime_ns)
            self._snapshot = snapshot
            return snapshot

    def get_countries(self) -> frozenset[str]:
        return self.get_snapshot().countries

    def clear_cache(self) -> None:
        with self._lock:
            self._snapshot = None

    def _load(self, mtime_ns: int) -> T1CountryConfigSnapshot:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        countries = _parse_country_codes(data)
        return T1CountryConfigSnapshot(
            path=self.path,
            mtime_ns=mtime_ns,
            version=_optional_int(data.get("version")),
            status=str(data.get("status")) if data.get("status") is not None else None,
            countries=frozenset(countries),
        )


_LOADERS: dict[Path, T1CountryConfigLoader] = {}
_LOADERS_LOCK = RLock()


def get_t1_country_loader(path: Path) -> T1CountryConfigLoader:
    resolved = path.resolve()
    with _LOADERS_LOCK:
        loader = _LOADERS.get(resolved)
        if loader is None:
            loader = T1CountryConfigLoader(resolved)
            _LOADERS[resolved] = loader
        return loader


def load_t1_countries_hot(path: Path) -> frozenset[str]:
    return get_t1_country_loader(path).get_countries()


def clear_t1_country_loader_cache(path: Path | None = None) -> None:
    with _LOADERS_LOCK:
        if path is None:
            for loader in _LOADERS.values():
                loader.clear_cache()
            _LOADERS.clear()
            return
        loader = _LOADERS.get(path.resolve())
        if loader is not None:
            loader.clear_cache()


def _parse_country_codes(data: dict[str, Any]) -> set[str]:
    raw = data.get("countries")
    if not isinstance(raw, list):
        raise ValueError("t1_countries.json must contain a countries list")
    codes: set[str] = set()
    for item in raw:
        code = str(item).strip().upper()
        if not code:
            continue
        if len(code) != 2 or not code.isalpha():
            raise ValueError(f"invalid ISO-3166 alpha-2 country code: {item}")
        codes.add(code)
    return codes


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
