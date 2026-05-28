"""Unified safety filter for P3-12."""

from __future__ import annotations

import json
import os
import re
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from services.content_safety import evaluate_inbound_content_safety

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _default_redlines_path() -> Path:
    env_dir = os.environ.get("ERIS_CONFIG_DIR")
    candidates = []
    if env_dir:
        candidates.append(Path(env_dir) / "safety_filter_redlines.json")
    candidates.extend(
        [
            _REPO_ROOT / "config" / "safety_filter_redlines.json",
            Path(__file__).resolve().parents[1] / "config" / "safety_filter_redlines.json",
            Path("/app/config/safety_filter_redlines.json"),
        ]
    )
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


DEFAULT_REDLINES_PATH = _default_redlines_path()


@dataclass(frozen=True)
class SafetyRedline:
    id: str
    category: str
    reason: str
    patterns: tuple[re.Pattern[str], ...] = field(default_factory=tuple)
    enabled: bool = True


@dataclass(frozen=True)
class SafetyFilterResult:
    blocked: bool
    block_reason: str | None
    redline_id: str | None = None
    category: str | None = None
    layers: dict[str, Any] = field(default_factory=dict)


class SafetyFilter:
    def __init__(self, redlines_path: Path = DEFAULT_REDLINES_PATH) -> None:
        self.redlines_path = Path(redlines_path)
        self._mtime_ns: int | None = None
        self._digest: str | None = None
        self._redlines: tuple[SafetyRedline, ...] = ()

    def load_if_changed(self) -> tuple[SafetyRedline, ...]:
        stat = self.redlines_path.stat()
        content = self.redlines_path.read_text(encoding="utf-8")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if stat.st_mtime_ns != self._mtime_ns or digest != self._digest:
            raw = json.loads(content)
            self._redlines = tuple(_redline_from_dict(item) for item in raw.get("redlines", []))
            self._mtime_ns = stat.st_mtime_ns
            self._digest = digest
            logger.bind(
                component="safety_filter",
                redlines=len(self._redlines),
                version=raw.get("version"),
            ).info("safety_filter.redlines.loaded")
        return self._redlines

    async def evaluate(self, text: str, *, trace_id: str) -> SafetyFilterResult:
        local = self._evaluate_redlines(text)
        if local.blocked:
            return local

        inbound = await evaluate_inbound_content_safety(text, trace_id=trace_id)
        if inbound.get("blocked"):
            return SafetyFilterResult(
                blocked=True,
                block_reason=inbound.get("block_reason"),
                category="content_safety",
                layers={"content_safety": inbound},
            )
        return SafetyFilterResult(
            blocked=False,
            block_reason=None,
            layers={"redline": {"blocked": False}, "content_safety": inbound},
        )

    def _evaluate_redlines(self, text: str) -> SafetyFilterResult:
        value = text or ""
        for redline in self.load_if_changed():
            if not redline.enabled:
                continue
            if any(pattern.search(value) for pattern in redline.patterns):
                return SafetyFilterResult(
                    blocked=True,
                    block_reason=redline.reason,
                    redline_id=redline.id,
                    category=redline.category,
                    layers={"redline": {"id": redline.id, "category": redline.category}},
                )
        return SafetyFilterResult(blocked=False, block_reason=None)


async def evaluate_safety_filter(text: str, *, trace_id: str) -> SafetyFilterResult:
    return safety_filter.evaluate(text, trace_id=trace_id)


def _redline_from_dict(data: dict[str, Any]) -> SafetyRedline:
    return SafetyRedline(
        id=str(data["id"]),
        category=str(data["category"]),
        reason=str(data["reason"]),
        patterns=tuple(re.compile(str(p), re.I | re.U) for p in data.get("patterns", [])),
        enabled=bool(data.get("enabled", True)),
    )


safety_filter = SafetyFilter()
