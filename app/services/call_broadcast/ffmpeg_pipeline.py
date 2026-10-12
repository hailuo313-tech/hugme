"""FFmpeg normalization for Telegram video-call playback via PyTgCalls."""

from __future__ import annotations

import asyncio
import json
import math
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

from loguru import logger

_FFMPEG_TRANSCODE_SLOTS = 2
_ffmpeg_transcode_semaphore: asyncio.Semaphore | None = None
_sync_transcode_semaphore = threading.Semaphore(_FFMPEG_TRANSCODE_SLOTS)


def _transcode_semaphore() -> asyncio.Semaphore:
    global _ffmpeg_transcode_semaphore
    if _ffmpeg_transcode_semaphore is None:
        _ffmpeg_transcode_semaphore = asyncio.Semaphore(_FFMPEG_TRANSCODE_SLOTS)
    return _ffmpeg_transcode_semaphore


def cached_transcode_output_path(source_path: str, work_dir: str) -> Path:
    """Stable on-disk cache path keyed by source file identity + mtime."""
    path = Path(source_path)
    stat = path.stat()
    return Path(work_dir) / f"{path.stem}_{stat.st_mtime_ns}_720p.mp4"


def cached_leadin_output_path(source_path: str, work_dir: str, delay_seconds: float) -> Path:
    """Stable cache path for media with a silent black post-connect lead-in."""
    path = Path(source_path)
    stat = path.stat()
    delay_ms = max(0, int(round(float(delay_seconds) * 1000)))
    return Path(work_dir) / f"{path.stem}_{stat.st_mtime_ns}_lead{delay_ms}.mp4"

TELEGRAM_CALL_TARGET_HEIGHT = 720
TELEGRAM_CALL_TARGET_WIDTH = 1280
TELEGRAM_CALL_TARGET_FPS = 30
TELEGRAM_CALL_VIDEO_MAXRATE = "2500k"
TELEGRAM_CALL_VIDEO_BUFSIZE = "5000k"
TELEGRAM_CALL_VIDEO_CRF = "23"
TELEGRAM_CALL_AUDIO_BITRATE = "128k"


def video_scale_filter(*, width: int | None, height: int | None) -> str:
    """Pick a lanczos scale filter that fits Telegram's 720p call ceiling."""
    if width and height and width >= height:
        return f"scale={TELEGRAM_CALL_TARGET_WIDTH}:-2:flags=lanczos"
    return f"scale=-2:{TELEGRAM_CALL_TARGET_HEIGHT}:flags=lanczos"


def _parse_frame_rate(raw: str | None) -> float | None:
    if not raw:
        return None
    if "/" in raw:
        num, den = raw.split("/", 1)
        try:
            denominator = float(den)
            if denominator <= 0:
                return None
            return float(num) / denominator
        except ValueError:
            return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 and math.isfinite(value) else None


def is_telegram_call_ready(info: dict[str, Any] | None) -> bool:
    """True when the file already fits Telegram 720p/30fps call streaming."""
    if not info:
        return False
    width = int(info.get("width") or 0)
    height = int(info.get("height") or 0)
    if width <= 0 or height <= 0:
        return False
    if width > TELEGRAM_CALL_TARGET_WIDTH or height > TELEGRAM_CALL_TARGET_HEIGHT:
        return False
    fps = info.get("fps")
    if fps is None or abs(float(fps) - TELEGRAM_CALL_TARGET_FPS) > 2.0:
        return False
    codec = str(info.get("codec_name") or "").lower()
    return codec in {"h264", "avc1"}


def build_transcode_command(
    source_path: str,
    target_path: str,
    *,
    scale_filter: str,
    has_audio: bool = True,
) -> list[str]:
    video_args = [
        "-vf",
        scale_filter,
        "-r",
        str(TELEGRAM_CALL_TARGET_FPS),
        "-c:v",
        "libx264",
        "-preset",
        "faster",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        TELEGRAM_CALL_VIDEO_CRF,
        "-maxrate",
        TELEGRAM_CALL_VIDEO_MAXRATE,
        "-bufsize",
        TELEGRAM_CALL_VIDEO_BUFSIZE,
    ]
    audio_args = [
        "-c:a",
        "aac",
        "-b:a",
        TELEGRAM_CALL_AUDIO_BITRATE,
        "-ar",
        "48000",
    ]
    tail = ["-movflags", "+faststart", target_path]

    if has_audio:
        return [
            "ffmpeg",
            "-y",
            "-i",
            source_path,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            *video_args,
            *audio_args,
            *tail,
        ]

    return [
        "ffmpeg",
        "-y",
        "-i",
        source_path,
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        *video_args,
        *audio_args,
        "-shortest",
        *tail,
    ]


def build_leadin_command(
    source_path: str,
    target_path: str,
    *,
    delay_seconds: float,
    has_audio: bool,
) -> list[str]:
    """Prepend black/silent media so PyTgCalls only needs one ``play`` call."""
    delay = max(0.0, float(delay_seconds))
    delay_ms = int(round(delay * 1000))
    video_args = [
        "-vf",
        f"tpad=start_mode=add:start_duration={delay:.3f}:color=black",
        "-r",
        str(TELEGRAM_CALL_TARGET_FPS),
        "-c:v",
        "libx264",
        "-preset",
        "faster",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        TELEGRAM_CALL_VIDEO_CRF,
        "-maxrate",
        TELEGRAM_CALL_VIDEO_MAXRATE,
        "-bufsize",
        TELEGRAM_CALL_VIDEO_BUFSIZE,
    ]
    audio_args = [
        "-c:a",
        "aac",
        "-b:a",
        TELEGRAM_CALL_AUDIO_BITRATE,
        "-ar",
        "48000",
    ]
    tail = ["-movflags", "+faststart", target_path]
    if has_audio:
        return [
            "ffmpeg",
            "-y",
            "-i",
            source_path,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            *video_args,
            "-af",
            f"adelay={delay_ms}:all=1",
            *audio_args,
            *tail,
        ]
    return [
        "ffmpeg",
        "-y",
        "-i",
        source_path,
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        *video_args,
        *audio_args,
        "-shortest",
        *tail,
    ]


def ensure_post_connect_leadin_sync(
    source_path: str,
    *,
    delay_seconds: float,
    work_dir: str,
    trace_id: str | None = None,
) -> str:
    """Return cached playable media with a black/silent lead-in."""
    if delay_seconds <= 0:
        return source_path
    path = Path(source_path)
    if not path.is_file():
        raise FileNotFoundError(f"video asset not found: {source_path}")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not available for post-connect media delay")
    out_dir = Path(work_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = cached_leadin_output_path(str(path), work_dir, delay_seconds)
    if target.is_file() and target.stat().st_mtime >= path.stat().st_mtime:
        return str(target)
    command = build_leadin_command(
        str(path),
        str(target),
        delay_seconds=delay_seconds,
        has_audio=probe_has_audio_stream_sync(str(path)),
    )
    logger.bind(
        trace_id=trace_id,
        source=str(path),
        target=str(target),
        delay_seconds=delay_seconds,
    ).info("call_broadcast.ffmpeg.leadin_start")
    with _sync_transcode_semaphore:
        proc = subprocess.run(command, capture_output=True, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or b"").decode("utf-8", errors="replace")[-500:]
        raise RuntimeError(f"ffmpeg lead-in failed: {detail}")
    logger.bind(trace_id=trace_id, target=str(target)).info(
        "call_broadcast.ffmpeg.leadin_done"
    )
    return str(target)


def probe_video_duration_seconds_sync(source_path: str) -> float | None:
    """Return media duration in seconds via ffprobe (blocking, thread-safe)."""
    path = Path(source_path)
    if not path.is_file() or shutil.which("ffprobe") is None:
        return None

    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        return None
    try:
        value = float(proc.stdout.decode("utf-8", errors="replace").strip())
    except ValueError:
        return None
    if value <= 0 or not math.isfinite(value):
        return None
    return value


async def probe_video_duration_seconds(source_path: str) -> float | None:
    """Return media duration in seconds via ffprobe, or None if unavailable."""
    return await asyncio.to_thread(probe_video_duration_seconds_sync, source_path)


def _parse_probe_stream_payload(stdout: bytes) -> dict[str, Any] | None:
    if not stdout:
        return None
    try:
        payload = json.loads(stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None

    streams = payload.get("streams") or []
    stream = streams[0] if streams else {}
    fmt = payload.get("format") or {}
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    fps = _parse_frame_rate(str(stream.get("r_frame_rate") or ""))
    duration_raw = fmt.get("duration")
    try:
        duration = float(duration_raw) if duration_raw is not None else None
    except (TypeError, ValueError):
        duration = None

    bit_rate_raw = stream.get("bit_rate") or fmt.get("bit_rate")
    try:
        bit_rate = int(bit_rate_raw) if bit_rate_raw is not None else None
    except (TypeError, ValueError):
        bit_rate = None

    return {
        "width": width,
        "height": height,
        "fps": fps,
        "codec_name": stream.get("codec_name"),
        "bit_rate": bit_rate,
        "duration": duration,
    }


def probe_video_stream_info_sync(source_path: str) -> dict[str, Any] | None:
    """Return basic video stream metadata (blocking, thread-safe)."""
    path = Path(source_path)
    if not path.is_file() or shutil.which("ffprobe") is None:
        return None

    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,codec_name,r_frame_rate,bit_rate",
            "-show_entries",
            "format=duration,bit_rate",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return _parse_probe_stream_payload(proc.stdout)


async def probe_video_stream_info(source_path: str) -> dict[str, Any] | None:
    """Return basic video stream metadata for normalization decisions."""
    return await asyncio.to_thread(probe_video_stream_info_sync, source_path)


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


def probe_has_audio_stream_sync(source_path: str) -> bool:
    path = Path(source_path)
    if not path.is_file() or shutil.which("ffprobe") is None:
        return False

    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        return False
    return proc.stdout.decode("utf-8", errors="replace").strip().lower() == "audio"


async def probe_has_audio_stream(source_path: str) -> bool:
    return await asyncio.to_thread(probe_has_audio_stream_sync, source_path)


def _run_transcode_sync(
    source_path: str,
    target_path: str,
    *,
    scale_filter: str,
    has_audio: bool,
    trace_id: str | None,
) -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not available")

    cmd = build_transcode_command(
        source_path,
        target_path,
        scale_filter=scale_filter,
        has_audio=has_audio,
    )
    logger.bind(trace_id=trace_id, source=source_path, target=target_path).info(
        "call_broadcast.ffmpeg.transcode_start"
    )
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or b"").decode("utf-8", errors="replace")[-500:]
        raise RuntimeError(f"ffmpeg transcode failed: {detail}")
    logger.bind(trace_id=trace_id, target=target_path).info("call_broadcast.ffmpeg.transcode_done")


async def _run_transcode(
    source_path: str,
    target_path: str,
    *,
    scale_filter: str,
    has_audio: bool,
    trace_id: str | None,
) -> None:
    await asyncio.to_thread(
        _run_transcode_sync,
        source_path,
        target_path,
        scale_filter=scale_filter,
        has_audio=has_audio,
        trace_id=trace_id,
    )


def normalize_video_for_telegram_call_sync(
    source_path: str,
    *,
    trace_id: str | None = None,
    in_place: bool = False,
    work_dir: str = "/tmp/call_broadcast",
) -> tuple[str, dict[str, Any]]:
    """Normalize a local video for Telegram 720p/30fps call playback (blocking)."""
    path = Path(source_path)
    if not path.is_file():
        raise FileNotFoundError(f"video asset not found: {source_path}")

    stream_info = probe_video_stream_info_sync(str(path))
    has_audio = probe_has_audio_stream_sync(str(path))
    profile: dict[str, Any] = {
        "target": "telegram_call_720p30",
        "target_height": TELEGRAM_CALL_TARGET_HEIGHT,
        "target_width": TELEGRAM_CALL_TARGET_WIDTH,
        "target_fps": TELEGRAM_CALL_TARGET_FPS,
        "video_maxrate": TELEGRAM_CALL_VIDEO_MAXRATE,
        "source": stream_info or {},
        "has_audio": has_audio,
        "normalized": False,
    }

    if is_telegram_call_ready(stream_info):
        profile["normalized"] = True
        profile["skipped"] = True
        return str(path), profile

    if shutil.which("ffmpeg") is None:
        profile["skipped"] = True
        profile["reason"] = "ffmpeg_unavailable"
        return str(path), profile

    if in_place:
        target = path.with_name(f"{path.stem}.normalizing{path.suffix or '.mp4'}")
    else:
        out_dir = Path(work_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        target = cached_transcode_output_path(str(path), work_dir)
        if target.is_file() and target.stat().st_mtime >= path.stat().st_mtime:
            normalized_info = probe_video_stream_info_sync(str(target))
            profile["normalized"] = True
            profile["output"] = normalized_info or {}
            profile["cache_hit"] = True
            return str(target), profile

    scale = video_scale_filter(
        width=int(stream_info.get("width") or 0) if stream_info else None,
        height=int(stream_info.get("height") or 0) if stream_info else None,
    )
    profile["scale_filter"] = scale

    with _sync_transcode_semaphore:
        _run_transcode_sync(
            str(path),
            str(target),
            scale_filter=scale,
            has_audio=has_audio,
            trace_id=trace_id,
        )

    if in_place:
        target.replace(path)
        final_path = str(path)
    else:
        final_path = str(target)

    normalized_info = probe_video_stream_info_sync(final_path)
    profile["normalized"] = True
    profile["output"] = normalized_info or {}
    return final_path, profile


async def normalize_video_for_telegram_call(
    source_path: str,
    *,
    trace_id: str | None = None,
    in_place: bool = False,
    work_dir: str = "/tmp/call_broadcast",
) -> tuple[str, dict[str, Any]]:
    """Normalize a local video for Telegram 720p/30fps call playback."""
    return await asyncio.to_thread(
        normalize_video_for_telegram_call_sync,
        source_path,
        trace_id=trace_id,
        in_place=in_place,
        work_dir=work_dir,
    )


def ensure_playable_video_sync(
    source_path: str,
    *,
    trace_id: str | None = None,
    transcode_enabled: bool = True,
    work_dir: str = "/tmp/call_broadcast",
) -> str:
    """Return a Telegram-call-ready path (blocking, for thread-pool prep)."""
    if not transcode_enabled:
        path = Path(source_path)
        if not path.is_file():
            raise FileNotFoundError(f"video asset not found: {source_path}")
        return str(path)

    playable, _profile = normalize_video_for_telegram_call_sync(
        source_path,
        trace_id=trace_id,
        in_place=False,
        work_dir=work_dir,
    )
    return playable


async def ensure_playable_video(
    source_path: str,
    *,
    trace_id: str | None = None,
    transcode_enabled: bool = True,
    work_dir: str = "/tmp/call_broadcast",
) -> str:
    """Return a Telegram-call-ready path for PyTgCalls playback."""
    if not transcode_enabled:
        path = Path(source_path)
        if not path.is_file():
            raise FileNotFoundError(f"video asset not found: {source_path}")
        return str(path)

    playable, _profile = await normalize_video_for_telegram_call(
        source_path,
        trace_id=trace_id,
        in_place=False,
        work_dir=work_dir,
    )
    return playable
