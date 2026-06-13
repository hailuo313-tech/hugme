"""Optional FFmpeg normalization before PyTgCalls playback."""

from __future__ import annotations

import asyncio
import math
import shutil
from pathlib import Path

from loguru import logger


async def probe_video_duration_seconds(source_path: str) -> float | None:
    """Return media duration in seconds via ffprobe, or None if unavailable."""
    path = Path(source_path)
    if not path.is_file() or shutil.which("ffprobe") is None:
        return None

    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0 or not stdout:
        return None
    try:
        value = float(stdout.decode("utf-8", errors="replace").strip())
    except ValueError:
        return None
    if value <= 0 or not math.isfinite(value):
        return None
    return value


def resolve_playback_duration_seconds(
    *,
    probed_seconds: float | None,
    configured_seconds: int | None = None,
    default_seconds: int = 30,
    max_seconds: int = 600,
) -> float:
    """Pick call hold time: actual file length wins over DB/config default."""
    if probed_seconds is not None and probed_seconds > 0:
        return min(float(max_seconds), max(1.0, probed_seconds))
    if configured_seconds is not None and int(configured_seconds) > 0:
        return float(min(max_seconds, max(1, int(configured_seconds))))
    return float(min(max_seconds, max(1, int(default_seconds))))


async def ensure_playable_video(
    source_path: str,
    *,
    trace_id: str | None = None,
    transcode_enabled: bool = False,
    work_dir: str = "/tmp/call_broadcast",
) -> str:
    """Return a path PyTgCalls can play. Transcode only when enabled and ffmpeg exists."""
    path = Path(source_path)
    if not path.is_file():
        raise FileNotFoundError(f"video asset not found: {source_path}")

    if not transcode_enabled or shutil.which("ffmpeg") is None:
        return str(path)

    out_dir = Path(work_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{path.stem}_normalized.mp4"
    if target.is_file() and target.stat().st_mtime >= path.stat().st_mtime:
        return str(target)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(path),
        "-vf",
        "scale=640:360:force_original_aspect_ratio=decrease",
        "-r",
        "15",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-movflags",
        "+faststart",
        str(target),
    ]
    logger.bind(trace_id=trace_id, source=str(path)).info("call_broadcast.ffmpeg.transcode_start")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        detail = (stderr or b"").decode("utf-8", errors="replace")[-500:]
        raise RuntimeError(f"ffmpeg transcode failed: {detail}")
    logger.bind(trace_id=trace_id, target=str(target)).info("call_broadcast.ffmpeg.transcode_done")
    return str(target)
