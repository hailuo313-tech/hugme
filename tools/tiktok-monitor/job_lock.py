"""Non-blocking file lock to prevent overlapping worker jobs."""

from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional


def lock_path(root: Path, name: str) -> Path:
    path = root / "data" / f"{name}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def is_job_running(root: Path, name: str) -> bool:
    path = lock_path(root, name)
    if not path.exists():
        return False
    handle = open(path, "a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    finally:
        handle.close()


def running_job_pid(root: Path, name: str) -> Optional[int]:
    path = lock_path(root, name)
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return int(raw) if raw.isdigit() else None
    except OSError:
        return None


def pid_alive(pid: Optional[int]) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def cleanup_stale_lock(root: Path, name: str) -> None:
    """Remove lock file left behind by a dead worker process."""
    path = lock_path(root, name)
    if not path.exists():
        return
    pid = running_job_pid(root, name)
    if pid_alive(pid):
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


@contextmanager
def job_lock(root: Path, name: str) -> Iterator[bool]:
    path = lock_path(root, name)
    handle = open(path, "a+")
    acquired = False
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        yield True
    except BlockingIOError:
        yield False
    finally:
        if acquired:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
