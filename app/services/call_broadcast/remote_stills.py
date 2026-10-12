"""Capture the remote party's video during an auto-play call.

PyTgCalls ``record(RecordStream(camera=True, screen=True))`` delivers incoming
camera/screen frames as ``StreamFrames``. We:

- save the first JPEG immediately, then one every N seconds
- append every frame into an MJPEG stream and mux an MP4 on hangup
"""
from __future__ import annotations

import asyncio
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

from loguru import logger

from core.config import settings
from services.call_broadcast.ffmpeg_pipeline import probe_video_duration_seconds_sync

RECORDING_NAME = "remote.mp4"
MJPEG_NAME = "remote.mjpg"

_sessions: dict[tuple[str, int], "RemoteStillSession"] = {}
_bound_wrappers: set[int] = set()
_encode_lock = asyncio.Lock()


def remote_stills_enabled() -> bool:
    return bool(getattr(settings, "CALL_BROADCAST_REMOTE_STILL_ENABLED", True))


def remote_still_interval_seconds() -> float:
    return max(1.0, float(getattr(settings, "CALL_BROADCAST_REMOTE_STILL_INTERVAL_SECONDS", 10)))


def remote_still_max_count() -> int:
    return max(1, int(getattr(settings, "CALL_BROADCAST_REMOTE_STILL_MAX", 60)))


def stills_root() -> Path:
    root = Path(getattr(settings, "CALL_BROADCAST_VIDEO_ROOT", "/data/videos") or "/data/videos")
    return root / "call_stills"


def stills_dir_for_job(job_id: str) -> Path:
    return stills_root() / str(uuid.UUID(str(job_id)))


def still_file_path(job_id: str, index: int) -> Path:
    return stills_dir_for_job(job_id) / f"{int(index):03d}.jpg"


def recording_file_path(job_id: str) -> Path:
    return stills_dir_for_job(job_id) / RECORDING_NAME


def mjpeg_file_path(job_id: str) -> Path:
    return stills_dir_for_job(job_id) / MJPEG_NAME


def remote_record_enabled() -> bool:
    return bool(getattr(settings, "CALL_BROADCAST_REMOTE_RECORD_ENABLED", True))


def remote_record_max_seconds() -> float:
    return max(5.0, float(getattr(settings, "CALL_BROADCAST_REMOTE_RECORD_MAX_SECONDS", 180)))


def remote_record_max_frames() -> int:
    return max(1, int(getattr(settings, "CALL_BROADCAST_REMOTE_RECORD_MAX_FRAMES", 3600)))


def guess_raw_pix_fmt(size: int, width: int, height: int) -> str | None:
    pixels = int(width) * int(height)
    if pixels <= 0 or size <= 0:
        return None
    if size == pixels * 4:
        return "rgba"
    if size == pixels * 3:
        return "rgb24"
    if size == pixels * 3 // 2:
        return "yuv420p"
    aligned_w = (int(width) + 15) // 16 * 16
    aligned_pixels = aligned_w * int(height)
    if size == aligned_pixels * 4:
        return "rgba"
    if size == aligned_pixels * 3 // 2:
        return "yuv420p"
    return None


def still_rotate_mode() -> str:
    raw = str(getattr(settings, "CALL_BROADCAST_REMOTE_STILL_ROTATE", "cw90") or "cw90")
    return raw.strip().lower()


def still_rotate_filter(*, width: int, height: int) -> str | None:
    """Landscape phone frames are sideways; rotate to portrait."""
    mode = still_rotate_mode()
    if mode in {"none", "0", "off", "false"}:
        return None
    if int(width) <= int(height):
        return None
    if mode == "ccw90":
        return "transpose=2"
    return "transpose=1"


def _run_ffmpeg(command: list[str], payload: bytes | None = None) -> bool:
    proc = subprocess.run(command, input=payload, capture_output=True, check=False)
    return proc.returncode == 0


def encode_frame_to_jpeg(
    raw: bytes,
    *,
    width: int,
    height: int,
    dest: Path,
) -> bool:
    """Write one JPEG. Accepts JPEG bytes, or raw RGBA/RGB/I420."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = bytes(raw or b"")
    rotate = still_rotate_filter(width=width, height=height)
    vf: list[str] = ["-vf", rotate] if rotate else []

    if len(payload) >= 3 and payload[:2] == b"\xff\xd8":
        if not vf:
            dest.write_bytes(payload)
            return dest.is_file() and dest.stat().st_size > 32
        command = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            *vf,
            "-frames:v",
            "1",
            "-q:v",
            "5",
            str(dest),
        ]
        return _run_ffmpeg(command, payload) and dest.is_file() and dest.stat().st_size > 32

    pix_fmt = guess_raw_pix_fmt(len(payload), width, height)
    if pix_fmt is None:
        return False

    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        pix_fmt,
        "-s",
        f"{int(width)}x{int(height)}",
        "-i",
        "pipe:0",
        *vf,
        "-frames:v",
        "1",
        "-q:v",
        "5",
        str(dest),
    ]
    return _run_ffmpeg(command, payload) and dest.is_file() and dest.stat().st_size > 32


def probe_still_size(path: Path) -> tuple[int, int] | None:
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0 or not probe.stdout.strip():
        return None
    try:
        width_s, height_s = probe.stdout.strip().split(",")[:2]
        return int(width_s), int(height_s)
    except (TypeError, ValueError):
        return None


def apply_still_vf(path: Path, vf: str) -> bool:
    if not path.is_file() or not vf:
        return False
    tmp = path.with_suffix(".rot.jpg")
    ok = _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vf",
            vf,
            "-q:v",
            "5",
            str(tmp),
        ]
    )
    if not ok or not tmp.is_file() or tmp.stat().st_size <= 32:
        if tmp.exists():
            tmp.unlink()
        return False
    tmp.replace(path)
    return True


def rotate_still_file_to_portrait(path: Path) -> bool:
    """Rotate an already-saved landscape JPEG in place."""
    size = probe_still_size(path)
    if size is None:
        return False
    width, height = size
    rotate = still_rotate_filter(width=width, height=height)
    if not rotate:
        return False
    return apply_still_vf(path, rotate)


def recording_rotate_filter() -> str | None:
    mode = still_rotate_mode()
    if mode in {"none", "0", "off", "false"}:
        return None
    if mode == "ccw90":
        return "transpose=2:passthrough=portrait"
    return "transpose=1:passthrough=portrait"


def frame_to_jpeg_bytes(raw: bytes, *, width: int, height: int) -> bytes | None:
    """Return a JPEG payload. Does not rotate; video mux applies orientation."""
    payload = bytes(raw or b"")
    if len(payload) >= 3 and payload[:2] == b"\xff\xd8":
        return payload
    pix_fmt = guess_raw_pix_fmt(len(payload), width, height)
    if pix_fmt is None:
        return None
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        pix_fmt,
        "-s",
        f"{int(width)}x{int(height)}",
        "-i",
        "pipe:0",
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-c:v",
        "mjpeg",
        "-q:v",
        "5",
        "pipe:1",
    ]
    proc = subprocess.run(command, input=payload, capture_output=True, check=False)
    if proc.returncode != 0 or not proc.stdout or proc.stdout[:2] != b"\xff\xd8":
        return None
    return proc.stdout


def mux_mjpeg_to_mp4(
    mjpeg_path: Path,
    dest: Path,
    *,
    frame_count: int,
    elapsed_seconds: float,
) -> bool:
    if not mjpeg_path.is_file() or mjpeg_path.stat().st_size < 64 or frame_count <= 0:
        return False
    elapsed = max(0.2, float(elapsed_seconds or 0.0))
    fps = min(30.0, max(0.2, float(frame_count) / elapsed))
    rotate = recording_rotate_filter()
    vf = "scale=360:640:force_original_aspect_ratio=decrease,pad=360:640:(ow-iw)/2:(oh-ih)/2"
    if rotate:
        vf = f"{rotate},{vf}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "mjpeg",
        "-framerate",
        f"{fps:.4f}",
        "-i",
        str(mjpeg_path),
        "-vf",
        vf,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    ok = _run_ffmpeg(command) and dest.is_file() and dest.stat().st_size > 256
    if not ok and dest.exists():
        dest.unlink()
    return ok


def list_job_recording(job_id: str) -> dict[str, Any] | None:
    try:
        path = recording_file_path(job_id)
    except (TypeError, ValueError):
        return None
    if not path.is_file() or path.stat().st_size < 256:
        return None
    duration = None
    probed = probe_video_duration_seconds_sync(str(path))
    if probed is not None and probed > 0:
        duration = round(float(probed), 2)
    return {
        "url": f"/api/v1/call-broadcast/admin/call-history/{job_id}/recording",
        "size_bytes": int(path.stat().st_size),
        "duration_seconds": duration,
    }


def list_job_stills(job_id: str) -> list[dict[str, Any]]:
    try:
        directory = stills_dir_for_job(job_id)
    except (TypeError, ValueError):
        return []
    if not directory.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.jpg")):
        try:
            index = int(path.stem)
        except ValueError:
            continue
        items.append(
            {
                "index": index,
                "url": f"/api/v1/call-broadcast/admin/call-history/{job_id}/stills/{index}",
            }
        )
    return items


def resolve_still_file(job_id: str, index: int) -> Path | None:
    try:
        path = still_file_path(job_id, index).resolve()
        root = stills_dir_for_job(job_id).resolve()
    except (TypeError, ValueError, OSError):
        return None
    if root not in path.parents and path.parent != root:
        return None
    if not path.is_file():
        return None
    return path


def resolve_recording_file(job_id: str) -> Path | None:
    try:
        path = recording_file_path(job_id).resolve()
        root = stills_dir_for_job(job_id).resolve()
    except (TypeError, ValueError, OSError):
        return None
    if root not in path.parents and path.parent != root:
        return None
    if not path.is_file() or path.stat().st_size < 256:
        return None
    return path


@dataclass
class RemoteStillSession:
    account_id: str
    chat_id: int
    job_id: str
    trace_id: str | None = None
    pytgcalls: Any | None = None
    count: int = 0
    last_saved_mono: float = 0.0
    video_frames: int = 0
    video_started_mono: float = 0.0
    video_last_mono: float = 0.0
    closing: bool = False
    mjpeg_handle: BinaryIO | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def _session_key(account_id: str, chat_id: int) -> tuple[str, int]:
    return (str(account_id), int(chat_id))


def bind_remote_still_handler(pytgcalls: Any, account_id: str) -> bool:
    """Attach StreamFrames listener once per PyTgCalls wrapper."""
    wrapper_id = id(pytgcalls)
    if wrapper_id in _bound_wrappers:
        return True
    try:
        from pytgcalls import filters as pyc_filters
        from pytgcalls.types import Device, Direction, StreamFrames
    except Exception as exc:
        logger.bind(account_id=account_id, error_type=type(exc).__name__).warning(
            "call_broadcast.remote_still.import_failed"
        )
        return False

    handler_filter = pyc_filters.stream_frame(
        directions=Direction.INCOMING,
        devices=Device.CAMERA | Device.SCREEN,
    )

    @pytgcalls.on_update(handler_filter)
    async def _on_remote_frames(_client: Any, update: StreamFrames) -> None:
        await ingest_stream_frames(account_id=account_id, update=update)

    _bound_wrappers.add(wrapper_id)
    logger.bind(account_id=account_id).info("call_broadcast.remote_still.handler_bound")
    return True


async def start_remote_still_capture(
    *,
    pytgcalls: Any,
    account_id: str,
    chat_id: int,
    job_id: str | None,
    trace_id: str | None = None,
) -> RemoteStillSession | None:
    if not remote_stills_enabled():
        return None
    if pytgcalls is None or not job_id:
        return None
    try:
        uuid.UUID(str(job_id))
    except (TypeError, ValueError):
        return None

    bind_remote_still_handler(pytgcalls, str(account_id))
    key = _session_key(str(account_id), int(chat_id))
    previous = _sessions.pop(key, None)
    if previous is not None:
        previous.closing = True
        _close_mjpeg(previous)
    session = RemoteStillSession(
        account_id=str(account_id),
        chat_id=int(chat_id),
        job_id=str(job_id),
        trace_id=trace_id,
        pytgcalls=pytgcalls,
    )
    _sessions[key] = session
    stills_dir_for_job(str(job_id)).mkdir(parents=True, exist_ok=True)

    try:
        from pytgcalls.types import RecordStream

        record = getattr(pytgcalls, "record", None)
        if not callable(record):
            raise RuntimeError("pytgcalls.record missing")
        result = record(int(chat_id), RecordStream(camera=True, screen=True))
        if asyncio.iscoroutine(result):
            await result
        logger.bind(
            account_id=str(account_id),
            chat_id=int(chat_id),
            job_id=str(job_id),
            trace_id=trace_id,
        ).info("call_broadcast.remote_still.record_started")
    except Exception as exc:
        logger.bind(
            account_id=str(account_id),
            chat_id=int(chat_id),
            job_id=str(job_id),
            error_type=type(exc).__name__,
            trace_id=trace_id,
        ).warning("call_broadcast.remote_still.record_failed")
    return session


def _close_mjpeg(session: RemoteStillSession) -> Path | None:
    handle = session.mjpeg_handle
    session.mjpeg_handle = None
    if handle is None:
        return None
    try:
        handle.flush()
        handle.close()
    except Exception:
        pass
    path = mjpeg_file_path(session.job_id)
    return path if path.is_file() else None


def _still_stop_timeout_seconds() -> float:
    return max(2.0, float(getattr(settings, "CALL_BROADCAST_STILL_STOP_TIMEOUT_SECONDS", 10)))


def _record_stop_timeout_seconds() -> float:
    return min(5.0, _still_stop_timeout_seconds())


async def _stop_pytgcalls_record(pytgcalls: Any, chat_id: int) -> None:
    if pytgcalls is None:
        return
    record = getattr(pytgcalls, "record", None)
    if not callable(record):
        return
    try:
        from pytgcalls.types import RecordStream

        result = record(int(chat_id), RecordStream(camera=False, screen=False))
        if asyncio.iscoroutine(result):
            await asyncio.wait_for(result, timeout=_record_stop_timeout_seconds())
    except Exception:
        return


async def stop_remote_still_capture(*, account_id: str, chat_id: int) -> int:
    key = _session_key(str(account_id), int(chat_id))
    session = _sessions.get(key)
    if session is None:
        return 0
    session.closing = True
    mjpeg_path = None
    video_frames = session.video_frames
    elapsed = 0.0
    pytgcalls = session.pytgcalls
    job_id = session.job_id
    stills = session.count
    trace_id = session.trace_id
    locked = False
    try:
        await asyncio.wait_for(session.lock.acquire(), timeout=2.0)
        locked = True
    except asyncio.TimeoutError:
        logger.bind(account_id=str(account_id), chat_id=int(chat_id)).warning(
            "call_broadcast.remote_still.stop_lock_timeout"
        )
    try:
        if locked:
            mjpeg_path = _close_mjpeg(session)
            video_frames = session.video_frames
            if session.video_started_mono and session.video_last_mono:
                elapsed = max(0.0, session.video_last_mono - session.video_started_mono)
            pytgcalls = session.pytgcalls
            job_id = session.job_id
            stills = session.count
            trace_id = session.trace_id
        else:
            handle = session.mjpeg_handle
            session.mjpeg_handle = None
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
            mjpeg_path = mjpeg_file_path(session.job_id)
            if not mjpeg_path.is_file():
                mjpeg_path = None
    finally:
        if locked:
            session.lock.release()
    _sessions.pop(key, None)
    await _stop_pytgcalls_record(pytgcalls, int(chat_id))

    recorded = False
    recording_bytes = 0
    if remote_record_enabled() and mjpeg_path is not None and video_frames > 0:
        dest = recording_file_path(job_id)
        loop = asyncio.get_running_loop()
        mux_timeout = max(3.0, _still_stop_timeout_seconds() - 3.0)
        try:
            recorded = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: mux_mjpeg_to_mp4(
                        mjpeg_path,
                        dest,
                        frame_count=video_frames,
                        elapsed_seconds=elapsed or max(1.0, video_frames / 5.0),
                    ),
                ),
                timeout=mux_timeout,
            )
        except asyncio.TimeoutError:
            logger.bind(job_id=job_id, chat_id=int(chat_id)).warning(
                "call_broadcast.remote_still.mux_timeout"
            )
            recorded = False
        if recorded and dest.is_file():
            recording_bytes = dest.stat().st_size
    if mjpeg_path is not None and mjpeg_path.exists():
        try:
            mjpeg_path.unlink()
        except OSError:
            pass
    logger.bind(
        account_id=str(account_id),
        chat_id=int(chat_id),
        job_id=job_id,
        stills=stills,
        video_frames=video_frames,
        recorded=recorded,
        recording_bytes=recording_bytes,
        elapsed_seconds=round(elapsed, 2),
        trace_id=trace_id,
    ).info("call_broadcast.remote_still.stopped")
    return stills


async def ingest_stream_frames(*, account_id: str, update: Any) -> None:
    try:
        await _ingest_stream_frames(account_id=account_id, update=update)
    except Exception as exc:
        logger.bind(
            account_id=str(account_id),
            error_type=type(exc).__name__,
        ).warning("call_broadcast.remote_still.ingest_failed")


async def _ingest_stream_frames(*, account_id: str, update: Any) -> None:
    chat_id = int(getattr(update, "chat_id", 0) or 0)
    session = _sessions.get(_session_key(str(account_id), chat_id))
    frames = list(getattr(update, "frames", None) or [])
    if session is None:
        if frames:
            logger.bind(account_id=str(account_id), chat_id=chat_id).debug(
                "call_broadcast.remote_still.frame_no_session"
            )
        return
    if not frames:
        return

    now = time.monotonic()
    last_jpeg: bytes | None = None
    last_raw = b""
    last_width = 0
    last_height = 0
    encode_index: int | None = None
    encode_job_id = ""
    encode_trace_id = session.trace_id
    encode_video_frames = 0
    async with session.lock:
        if session.closing:
            return
        for frame in frames:
            raw = getattr(frame, "frame", b"") or b""
            info = getattr(frame, "info", None)
            width = int(getattr(info, "width", 0) or 0)
            height = int(getattr(info, "height", 0) or 0)
            if not raw:
                continue
            jpeg = frame_to_jpeg_bytes(raw, width=width, height=height)
            if jpeg is None:
                continue
            last_jpeg = jpeg
            last_raw = raw
            last_width = width
            last_height = height
            if remote_record_enabled() and _can_append_video(session, now):
                _append_mjpeg(session, jpeg)
                if session.video_started_mono <= 0:
                    session.video_started_mono = now
                session.video_last_mono = now
                session.video_frames += 1

        if last_jpeg is None:
            return
        if session.count >= remote_still_max_count():
            return
        if session.count > 0 and (now - session.last_saved_mono) < remote_still_interval_seconds():
            return
        encode_index = session.count
        encode_job_id = session.job_id
        encode_trace_id = session.trace_id
        encode_video_frames = session.video_frames

    if encode_index is None:
        return
    dest = still_file_path(encode_job_id, encode_index)
    loop = asyncio.get_running_loop()
    async with _encode_lock:
        ok = await loop.run_in_executor(
            None,
            lambda: encode_frame_to_jpeg(
                last_raw, width=last_width, height=last_height, dest=dest
            ),
        )
    async with session.lock:
        if session.closing:
            return
        if not ok:
            logger.bind(
                job_id=encode_job_id,
                width=last_width,
                height=last_height,
                bytes=len(last_raw),
            ).warning("call_broadcast.remote_still.encode_failed")
            return
        if session.count != encode_index:
            return
        session.count += 1
        session.last_saved_mono = now
        logger.bind(
            job_id=encode_job_id,
            index=encode_index,
            stills=session.count,
            video_frames=encode_video_frames,
            width=last_width,
            height=last_height,
            rotate=still_rotate_filter(width=last_width, height=last_height),
            trace_id=encode_trace_id,
        ).info("call_broadcast.remote_still.saved")


def _can_append_video(session: RemoteStillSession, now: float) -> bool:
    if session.video_frames >= remote_record_max_frames():
        return False
    if session.video_started_mono > 0 and (now - session.video_started_mono) >= remote_record_max_seconds():
        return False
    return True


def _append_mjpeg(session: RemoteStillSession, jpeg: bytes) -> None:
    if session.mjpeg_handle is None:
        path = mjpeg_file_path(session.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        session.mjpeg_handle = path.open("ab")
    session.mjpeg_handle.write(jpeg)
    if session.video_frames % 30 == 0:
        session.mjpeg_handle.flush()
