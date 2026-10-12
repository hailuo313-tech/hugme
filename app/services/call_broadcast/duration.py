"""Helpers for call playback timing and displayed duration."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CallPlaybackResult:
    """Resolved timing for one outbound video-call stream."""

    playback_seconds: float
    probed_seconds: float | None = None
    stream_wall_seconds: float | None = None

    def metadata_patch(self) -> dict[str, float | int]:
        patch: dict[str, float | int] = {
            "playback_seconds": display_playback_seconds(self.playback_seconds),
        }
        if self.probed_seconds is not None:
            patch["probed_seconds"] = round(float(self.probed_seconds), 2)
        if self.stream_wall_seconds is not None:
            patch["stream_wall_seconds"] = round(float(self.stream_wall_seconds), 1)
        return patch


def display_playback_seconds(value: float | int | None) -> int:
    """Round up so UI duration never understates the media file."""
    seconds = float(value or 0)
    if seconds <= 0:
        return 0
    return int(math.ceil(seconds - 1e-9))


def stored_asset_duration_seconds(
    *,
    probed_seconds: float | None,
    configured_seconds: int | None = None,
    default_seconds: int = 30,
    max_seconds: int = 600,
) -> int:
    """Persist asset duration using probe-first, ceil-to-second semantics."""
    from services.call_broadcast.ffmpeg_pipeline import resolve_playback_duration_seconds

    resolved = resolve_playback_duration_seconds(
        probed_seconds=probed_seconds,
        configured_seconds=configured_seconds,
        default_seconds=default_seconds,
        max_seconds=max_seconds,
    )
    return display_playback_seconds(resolved)
