#!/usr/bin/env python3
"""Force-clear stuck probe/audit state on the server."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from job_lock import cleanup_stale_lock
from live_db import cancel_stale_probe_runs, cleanup_stale_jobs, init_db

init_db(ROOT / "data" / "tiktok_live.sqlite")
cleanup_stale_jobs(ROOT / "data" / "tiktok_live.sqlite", max_minutes=0)
cancel_stale_probe_runs(ROOT / "data" / "tiktok_live.sqlite")
cleanup_stale_lock(ROOT, "probe")
cleanup_stale_lock(ROOT, "audit")
print("stale probe/audit state cleared")
