"""SQLite schema for TikTok live monitoring."""

from __future__ import annotations

import sqlite3
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from accounts_store import Account

DB_PATH_DEFAULT = Path("data/tiktok_live.sqlite")
MANAGED_DAILY_LIMIT = 700
MANAGED_ACTIVE_LIMIT = 600
MANAGED_CANDIDATE_LIMIT = 100
MANAGED_RESULT_COST_USD = 0.004


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    profile_url TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_probe_at TEXT,
    last_probe_status TEXT,
    last_probe_source TEXT,
    last_probe_error TEXT,
    consecutive_errors INTEGER NOT NULL DEFAULT 0,
    last_live_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS live_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    room_id TEXT,
    title TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    peak_viewers INTEGER,
    last_viewers INTEGER,
    sample_count INTEGER NOT NULL DEFAULT 0,
    miss_streak INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'live',
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS live_viewer_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    captured_at TEXT NOT NULL,
    viewer_count INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'webcast',
    FOREIGN KEY (session_id) REFERENCES live_sessions(id)
);

CREATE TABLE IF NOT EXISTS probe_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    accounts_checked INTEGER NOT NULL DEFAULT 0,
    live_found INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audit_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    accounts_checked INTEGER NOT NULL DEFAULT 0,
    removed_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS removed_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_run_id INTEGER,
    username TEXT NOT NULL,
    display_name TEXT,
    profile_url TEXT,
    reason TEXT NOT NULL,
    status_code INTEGER,
    detail TEXT,
    removed_at TEXT NOT NULL,
    FOREIGN KEY (audit_run_id) REFERENCES audit_runs(id)
);

CREATE TABLE IF NOT EXISTS managed_api_daily_usage (
    usage_day TEXT PRIMARY KEY,
    active_count INTEGER NOT NULL DEFAULT 0,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_removed_accounts_username ON removed_accounts(username);
CREATE INDEX IF NOT EXISTS idx_removed_accounts_removed_at ON removed_accounts(removed_at DESC);

CREATE INDEX IF NOT EXISTS idx_live_sessions_account ON live_sessions(account_id);
CREATE INDEX IF NOT EXISTS idx_live_sessions_status ON live_sessions(status);
CREATE INDEX IF NOT EXISTS idx_live_samples_session ON live_viewer_samples(session_id, captured_at);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        _ensure_column(conn, "live_sessions", "miss_streak", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "accounts", "account_group", "TEXT NOT NULL DEFAULT 'own'")
        _ensure_column(conn, "removed_accounts", "account_group", "TEXT NOT NULL DEFAULT 'own'")
        _ensure_column(conn, "live_sessions", "last_enter_count", "INTEGER")
        _ensure_column(conn, "live_sessions", "peak_enter_count", "INTEGER")
        _ensure_column(conn, "live_sessions", "last_enter_delta", "INTEGER")
        _ensure_column(conn, "live_viewer_samples", "enter_count", "INTEGER")
        _ensure_column(conn, "accounts", "last_probe_at", "TEXT")
        _ensure_column(conn, "accounts", "last_probe_status", "TEXT")
        _ensure_column(conn, "accounts", "last_probe_source", "TEXT")
        _ensure_column(conn, "accounts", "last_probe_error", "TEXT")
        _ensure_column(conn, "accounts", "consecutive_errors", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "accounts", "last_live_at", "TEXT")
        _ensure_column(conn, "accounts", "local_live_streak", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "accounts", "local_offline_streak", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "accounts", "last_managed_probe_at", "TEXT")
        _ensure_column(conn, "accounts", "last_managed_status", "TEXT")
        _ensure_column(conn, "accounts", "last_managed_error", "TEXT")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def sync_accounts(db_path: Path, accounts: list[Account]) -> None:
    ts = now_iso()
    with connect(db_path) as conn:
        for acc in accounts:
            conn.execute(
                """
                INSERT INTO accounts (username, display_name, profile_url, account_group, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    display_name=excluded.display_name,
                    profile_url=excluded.profile_url,
                    account_group=excluded.account_group,
                    updated_at=excluded.updated_at,
                    enabled=1
                """,
                (acc.username, acc.name, acc.url, acc.group, ts, ts),
            )
        usernames = {a.username.casefold() for a in accounts}
        rows = conn.execute("SELECT id, username FROM accounts").fetchall()
        for row in rows:
            if row["username"].casefold() not in usernames:
                conn.execute(
                    "UPDATE accounts SET enabled=0, updated_at=? WHERE id=?",
                    (ts, row["id"]),
                )


def list_accounts(db_path: Path, *, group: Optional[str] = None) -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        if group:
            return conn.execute(
                """
                SELECT id, username, display_name, profile_url, account_group, enabled,
                       last_probe_at, last_probe_status, last_probe_source,
                       last_probe_error, consecutive_errors, last_live_at,
                       created_at, updated_at
                FROM accounts
                WHERE enabled = 1 AND account_group = ?
                ORDER BY username COLLATE NOCASE
                """,
                (group,),
            ).fetchall()
        return conn.execute(
            """
            SELECT id, username, display_name, profile_url, account_group, enabled,
                   last_probe_at, last_probe_status, last_probe_source,
                   last_probe_error, consecutive_errors, last_live_at,
                   created_at, updated_at
            FROM accounts
            WHERE enabled = 1
            ORDER BY username COLLATE NOCASE
            """
        ).fetchall()


def _account_id(conn: sqlite3.Connection, username: str) -> Optional[int]:
    row = conn.execute(
        "SELECT id FROM accounts WHERE lower(username)=lower(?) AND enabled=1",
        (username,),
    ).fetchone()
    return int(row["id"]) if row else None


def record_local_probe(db_path: Path, username: str, outcome: str) -> tuple[int, int]:
    """Record consecutive conclusive local signals and return both streaks."""
    live_delta = 1 if outcome == "live" else 0
    offline_delta = 1 if outcome == "offline" else 0
    with connect(db_path) as conn:
        account_id = _account_id(conn, username)
        if account_id is None:
            return 0, 0
        conn.execute(
            """
            UPDATE accounts
            SET local_live_streak=CASE
                    WHEN ? = 1 THEN COALESCE(local_live_streak, 0) + 1 ELSE 0 END,
                local_offline_streak=CASE
                    WHEN ? = 1 THEN COALESCE(local_offline_streak, 0) + 1 ELSE 0 END
            WHERE id=?
            """,
            (live_delta, offline_delta, account_id),
        )
        row = conn.execute(
            """
            SELECT local_live_streak, local_offline_streak
            FROM accounts WHERE id=?
            """,
            (account_id,),
        ).fetchone()
        return int(row["local_live_streak"] or 0), int(row["local_offline_streak"] or 0)


def account_verification_state(db_path: Path, username: str) -> Optional[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(
            """
            SELECT username, last_probe_status, local_live_streak, local_offline_streak,
                   last_managed_probe_at, last_managed_status, last_managed_error
            FROM accounts
            WHERE lower(username)=lower(?) AND enabled=1
            """,
            (username,),
        ).fetchone()


def count_managed_live_accounts(db_path: Path) -> int:
    with connect(db_path) as conn:
        return int(
            conn.execute(
                """
                SELECT COUNT(*) FROM accounts
                WHERE enabled=1
                  AND last_probe_status='live'
                  AND last_managed_status='live'
                """
            ).fetchone()[0]
        )


def managed_recheck_interval_minutes(active_count: int) -> int:
    checks_per_account = max(1, MANAGED_ACTIVE_LIMIT // max(1, active_count))
    return max(15, int(math.ceil(1440 / checks_per_account)))


def managed_recheck_overview(db_path: Path) -> dict:
    active_count = count_managed_live_accounts(db_path)
    interval_minutes = managed_recheck_interval_minutes(active_count)
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT MIN(last_managed_probe_at) AS oldest_probe_at
            FROM accounts
            WHERE enabled=1
              AND last_probe_status='live'
              AND last_managed_status='live'
            """
        ).fetchone()
    oldest = row["oldest_probe_at"] if row else None
    next_at = None
    if oldest:
        try:
            checked_at = datetime.fromisoformat(oldest)
            if checked_at.tzinfo is None:
                checked_at = checked_at.replace(tzinfo=timezone.utc)
            next_at = (checked_at + timedelta(minutes=interval_minutes)).isoformat()
        except (TypeError, ValueError):
            next_at = None
    return {
        "active_count": active_count,
        "interval_minutes": interval_minutes,
        "next_recheck_at": next_at,
    }


def record_managed_probe(
    db_path: Path,
    username: str,
    *,
    outcome: str,
    error: Optional[str] = None,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE accounts
            SET last_managed_probe_at=?,
                last_managed_status=?,
                last_managed_error=?
            WHERE lower(username)=lower(?) AND enabled=1
            """,
            (now_iso(), outcome, str(error)[:500] if error else None, username),
        )


def reserve_managed_budget(
    db_path: Path,
    requested: int,
    *,
    category: str,
) -> int:
    """Atomically reserve paid results before an API call."""
    if requested <= 0:
        return 0
    if category not in {"active", "candidate"}:
        raise ValueError("managed budget category must be active or candidate")
    usage_day = datetime.now(timezone.utc).date().isoformat()
    column = "active_count" if category == "active" else "candidate_count"
    category_limit = MANAGED_ACTIVE_LIMIT if category == "active" else MANAGED_CANDIDATE_LIMIT
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT OR IGNORE INTO managed_api_daily_usage
            (usage_day, active_count, candidate_count, updated_at)
            VALUES (?, 0, 0, ?)
            """,
            (usage_day, now_iso()),
        )
        row = conn.execute(
            """
            SELECT active_count, candidate_count
            FROM managed_api_daily_usage WHERE usage_day=?
            """,
            (usage_day,),
        ).fetchone()
        active_count = int(row["active_count"] or 0)
        candidate_count = int(row["candidate_count"] or 0)
        total_remaining = max(0, MANAGED_DAILY_LIMIT - active_count - candidate_count)
        current_category = active_count if category == "active" else candidate_count
        category_remaining = max(0, category_limit - current_category)
        allowed = min(int(requested), total_remaining, category_remaining)
        if allowed > 0:
            conn.execute(
                f"""
                UPDATE managed_api_daily_usage
                SET {column}={column}+?, updated_at=?
                WHERE usage_day=?
                """,
                (allowed, now_iso(), usage_day),
            )
        return allowed


def managed_budget_stats(db_path: Path) -> dict:
    usage_day = datetime.now(timezone.utc).date().isoformat()
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT active_count, candidate_count
            FROM managed_api_daily_usage WHERE usage_day=?
            """,
            (usage_day,),
        ).fetchone()
    active_count = int(row["active_count"] or 0) if row else 0
    candidate_count = int(row["candidate_count"] or 0) if row else 0
    used = active_count + candidate_count
    return {
        "usage_day": usage_day,
        "active_count": active_count,
        "candidate_count": candidate_count,
        "used": used,
        "limit": MANAGED_DAILY_LIMIT,
        "remaining": max(0, MANAGED_DAILY_LIMIT - used),
        "estimated_cost_usd": round(used * MANAGED_RESULT_COST_USD, 3),
        "max_cost_usd": round(MANAGED_DAILY_LIMIT * MANAGED_RESULT_COST_USD, 2),
    }


def _open_session(conn: sqlite3.Connection, account_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, account_id, room_id, title, started_at, ended_at,
               peak_viewers, last_viewers, sample_count, miss_streak, status
        FROM live_sessions
        WHERE account_id=? AND status='live'
        ORDER BY id DESC
        LIMIT 1
        """,
        (account_id,),
    ).fetchone()


def _update_session_viewers(
    conn: sqlite3.Connection,
    session_id: int,
    viewer_count: Optional[int],
    enter_count: Optional[int] = None,
    enter_delta: Optional[int] = None,
) -> None:
    if viewer_count is not None:
        conn.execute(
            """
            UPDATE live_sessions
            SET last_viewers=?,
                peak_viewers=CASE
                    WHEN peak_viewers IS NULL THEN ?
                    WHEN ? > peak_viewers THEN ?
                    ELSE peak_viewers
                END
            WHERE id=?
            """,
            (viewer_count, viewer_count, viewer_count, viewer_count, session_id),
        )
    if enter_count is not None:
        conn.execute(
            """
            UPDATE live_sessions
            SET last_enter_count=?,
                last_enter_delta=?,
                peak_enter_count=CASE
                    WHEN peak_enter_count IS NULL THEN ?
                    WHEN ? > peak_enter_count THEN ?
                    ELSE peak_enter_count
                END
            WHERE id=?
            """,
            (enter_count, enter_delta, enter_count, enter_count, enter_count, session_id),
        )


def _insert_sample(
    conn: sqlite3.Connection,
    session_id: int,
    viewer_count: int,
    source: str,
    enter_count: Optional[int] = None,
) -> None:
    ts = now_iso()
    enter_delta = None
    if enter_count is not None:
        prev = conn.execute(
            """
            SELECT enter_count FROM live_viewer_samples
            WHERE session_id=? AND enter_count IS NOT NULL
            ORDER BY id DESC LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        if prev and prev["enter_count"] is not None:
            enter_delta = enter_count - int(prev["enter_count"])
    conn.execute(
        """
        INSERT INTO live_viewer_samples (session_id, captured_at, viewer_count, enter_count, source)
        VALUES (?, ?, ?, ?, ?)
        """,
        (session_id, ts, viewer_count, enter_count, source),
    )
    conn.execute(
        "UPDATE live_sessions SET sample_count = sample_count + 1 WHERE id=?",
        (session_id,),
    )
    _update_session_viewers(conn, session_id, viewer_count, enter_count, enter_delta)


def apply_probe_result(
    db_path: Path,
    *,
    username: str,
    is_live: bool,
    room_id: Optional[str],
    title: Optional[str],
    viewer_count: Optional[int],
    enter_count: Optional[int] = None,
    miss_threshold: int = 2,
    source: str = "web",
    error: Optional[str] = None,
) -> None:
    ts = now_iso()
    with connect(db_path) as conn:
        account_id = _account_id(conn, username)
        if account_id is None:
            return

        if error:
            conn.execute(
                """
                UPDATE accounts
                SET last_probe_at=?,
                    last_probe_status='unknown',
                    last_probe_source=?,
                    last_probe_error=?,
                    consecutive_errors=COALESCE(consecutive_errors, 0) + 1
                WHERE id=?
                """,
                (ts, source, str(error)[:500], account_id),
            )
            return

        probe_status = "live" if is_live else "offline"
        conn.execute(
            """
            UPDATE accounts
            SET last_probe_at=?,
                last_probe_status=?,
                last_probe_source=?,
                last_probe_error=NULL,
                consecutive_errors=0,
                last_live_at=CASE WHEN ? THEN ? ELSE last_live_at END
            WHERE id=?
            """,
            (ts, probe_status, source, 1 if is_live else 0, ts, account_id),
        )

        session = _open_session(conn, account_id)
        if is_live:
            if session is None:
                conn.execute(
                    """
                    INSERT INTO live_sessions
                    (account_id, room_id, title, started_at, peak_viewers, last_viewers,
                     peak_enter_count, last_enter_count, status, miss_streak)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'live', 0)
                    """,
                    (
                        account_id,
                        room_id,
                        title,
                        ts,
                        viewer_count,
                        viewer_count,
                        enter_count,
                        enter_count,
                    ),
                )
                session_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            else:
                session_id = int(session["id"])
                conn.execute(
                    """
                    UPDATE live_sessions
                    SET room_id=COALESCE(?, room_id),
                        title=COALESCE(?, title),
                        miss_streak=0
                    WHERE id=?
                    """,
                    (room_id, title, session_id),
                )
            if viewer_count is not None or enter_count is not None:
                _insert_sample(
                    conn,
                    session_id,
                    int(viewer_count or 0),
                    "probe",
                    enter_count,
                )
            return

        if session is None:
            return
        session_id = int(session["id"])
        miss = int(session["miss_streak"] or 0) + 1
        if miss >= miss_threshold:
            conn.execute(
                """
                UPDATE live_sessions
                SET status='ended', ended_at=?, miss_streak=?
                WHERE id=?
                """,
                (ts, miss, session_id),
            )
        else:
            conn.execute(
                "UPDATE live_sessions SET miss_streak=? WHERE id=?",
                (miss, session_id),
            )


def record_sample(
    db_path: Path,
    session_id: int,
    viewer_count: int,
    source: str = "webcast",
    enter_count: Optional[int] = None,
) -> None:
    with connect(db_path) as conn:
        _insert_sample(conn, session_id, viewer_count, source, enter_count)


def list_active_sessions(db_path: Path) -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(
            """
            SELECT s.id, s.room_id, s.title, s.started_at, s.peak_viewers, s.last_viewers,
                   s.peak_enter_count, s.last_enter_count, s.sample_count,
                   a.username, a.display_name, a.last_probe_at, a.last_probe_status,
                   a.last_probe_source, a.last_probe_error
            FROM live_sessions s
            JOIN accounts a ON a.id = s.account_id
            WHERE s.status='live'
            ORDER BY s.started_at DESC
            """
        ).fetchall()


def list_live_sessions(
    db_path: Path,
    *,
    status: Optional[str] = None,
    group: Optional[str] = None,
    limit: int = 100,
) -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        group_clause = " AND a.account_group = ?" if group else ""
        params: list[object] = []
        if status:
            params.append(status)
            if group:
                params.append(group)
            params.append(limit)
            return conn.execute(
                f"""
                SELECT s.id, a.username, a.display_name, a.account_group, s.room_id, s.title,
                       s.started_at, s.ended_at, s.peak_viewers, s.last_viewers,
                       s.peak_enter_count, s.last_enter_count, s.last_enter_delta,
                       s.sample_count, s.status, a.last_probe_at, a.last_probe_status,
                       a.last_probe_source, a.last_probe_error
                FROM live_sessions s
                JOIN accounts a ON a.id = s.account_id
                WHERE s.status=?
                  AND (? != 'live' OR a.last_probe_status = 'live'){group_clause}
                ORDER BY s.started_at DESC
                LIMIT ?
                """,
                tuple([status, *params]),
            ).fetchall()
        if group:
            params.append(group)
        params.append(limit)
        return conn.execute(
            f"""
            SELECT s.id, a.username, a.display_name, a.account_group, s.room_id, s.title,
                   s.started_at, s.ended_at, s.peak_viewers, s.last_viewers,
                   s.peak_enter_count, s.last_enter_count, s.last_enter_delta,
                   s.sample_count, s.status, a.last_probe_at, a.last_probe_status,
                   a.last_probe_source, a.last_probe_error
            FROM live_sessions s
            JOIN accounts a ON a.id = s.account_id
            WHERE 1=1{group_clause}
            ORDER BY s.started_at DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()


def last_probe_run(db_path: Path) -> Optional[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(
            """
            SELECT id, started_at, finished_at, accounts_checked, live_found, errors
            FROM probe_runs
            WHERE finished_at IS NOT NULL
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()


def probe_in_progress(db_path: Path) -> bool:
    return get_active_probe_run(db_path) is not None


def audit_in_progress(db_path: Path) -> bool:
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT id FROM audit_runs
            WHERE finished_at IS NULL
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        return row is not None


def start_probe_run(db_path: Path) -> int:
    ts = now_iso()
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO probe_runs (started_at) VALUES (?)",
            (ts,),
        )
        return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def finish_probe_run(
    db_path: Path,
    run_id: int,
    accounts_checked: int,
    live_found: int,
    errors: int,
) -> None:
    ts = now_iso()
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE probe_runs
            SET finished_at=?, accounts_checked=?, live_found=?, errors=?
            WHERE id=?
            """,
            (ts, accounts_checked, live_found, errors, run_id),
        )


def cancel_stale_probe_runs(db_path: Path) -> None:
    """Close probe runs left open by crashed workers."""
    ts = now_iso()
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE probe_runs
            SET finished_at=?, errors=COALESCE(errors, 0) + 1
            WHERE finished_at IS NULL
            """,
            (ts,),
        )


def _parse_iso(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def cleanup_stale_jobs(db_path: Path, *, max_minutes: int = 12) -> None:
    """Mark long-running probe/audit jobs as failed so UI does not stay stuck."""
    cutoff = datetime.now(timezone.utc).timestamp() - max_minutes * 60
    ts = now_iso()
    with connect(db_path) as conn:
        probe_rows = conn.execute(
            "SELECT id, started_at FROM probe_runs WHERE finished_at IS NULL"
        ).fetchall()
        for row in probe_rows:
            started = _parse_iso(str(row["started_at"]))
            if started and started.timestamp() <= cutoff:
                conn.execute(
                    "UPDATE probe_runs SET finished_at=?, errors=COALESCE(errors, 0) + 1 WHERE id=?",
                    (ts, row["id"]),
                )
        audit_rows = conn.execute(
            "SELECT id, started_at FROM audit_runs WHERE finished_at IS NULL"
        ).fetchall()
        for row in audit_rows:
            started = _parse_iso(str(row["started_at"]))
            if started and started.timestamp() <= cutoff:
                conn.execute(
                    "UPDATE audit_runs SET finished_at=?, error_count=COALESCE(error_count, 0) + 1 WHERE id=?",
                    (ts, row["id"]),
                )


def get_active_probe_run(db_path: Path) -> Optional[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(
            """
            SELECT id, started_at, finished_at, accounts_checked, live_found, errors
            FROM probe_runs
            WHERE finished_at IS NULL
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()


def update_probe_progress(
    db_path: Path,
    run_id: int,
    accounts_checked: int,
    live_found: int,
    errors: int,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE probe_runs
            SET accounts_checked=?, live_found=?, errors=?
            WHERE id=?
            """,
            (accounts_checked, live_found, errors, run_id),
        )


def stats(db_path: Path, *, group: Optional[str] = None) -> dict:
    with connect(db_path) as conn:
        if group:
            account_count = conn.execute(
                "SELECT COUNT(*) FROM accounts WHERE enabled = 1 AND account_group = ?",
                (group,),
            ).fetchone()[0]
            live_now = conn.execute(
                """
                SELECT COUNT(*) FROM live_sessions s
                JOIN accounts a ON a.id = s.account_id
                WHERE s.status = 'live'
                  AND a.last_probe_status = 'live'
                  AND a.account_group = ?
                """,
                (group,),
            ).fetchone()[0]
            session_total = conn.execute(
                """
                SELECT COUNT(*) FROM live_sessions s
                JOIN accounts a ON a.id = s.account_id
                WHERE a.account_group = ?
                """,
                (group,),
            ).fetchone()[0]
            sample_total = conn.execute(
                """
                SELECT COUNT(*) FROM live_viewer_samples v
                JOIN live_sessions s ON s.id = v.session_id
                JOIN accounts a ON a.id = s.account_id
                WHERE a.account_group = ?
                """,
                (group,),
            ).fetchone()[0]
            removed_total = conn.execute(
                "SELECT COUNT(*) FROM removed_accounts WHERE account_group = ?",
                (group,),
            ).fetchone()[0]
        else:
            account_count = conn.execute(
                "SELECT COUNT(*) FROM accounts WHERE enabled = 1"
            ).fetchone()[0]
            live_now = conn.execute(
                """
                SELECT COUNT(*) FROM live_sessions s
                JOIN accounts a ON a.id = s.account_id
                WHERE s.status = 'live' AND a.last_probe_status = 'live'
                """
            ).fetchone()[0]
            session_total = conn.execute(
                "SELECT COUNT(*) FROM live_sessions"
            ).fetchone()[0]
            sample_total = conn.execute(
                "SELECT COUNT(*) FROM live_viewer_samples"
            ).fetchone()[0]
            removed_total = count_removed_accounts(db_path)
        status_group_clause = " AND account_group = ?" if group else ""
        status_params: tuple[object, ...] = (group,) if group else ()
        offline_count = conn.execute(
            f"""
            SELECT COUNT(*) FROM accounts
            WHERE enabled=1 AND last_probe_status='offline'{status_group_clause}
            """,
            status_params,
        ).fetchone()[0]
        unknown_count = conn.execute(
            f"""
            SELECT COUNT(*) FROM accounts
            WHERE enabled=1 AND last_probe_status='unknown'{status_group_clause}
            """,
            status_params,
        ).fetchone()[0]
        stale_count = conn.execute(
            f"""
            SELECT COUNT(*) FROM accounts
            WHERE enabled=1
              AND (
                  last_probe_at IS NULL
                  OR datetime(last_probe_at) < datetime('now', '-3 minutes')
              ){status_group_clause}
            """,
            status_params,
        ).fetchone()[0]
    probe = last_probe_run(db_path)
    audit = last_audit_run(db_path)
    return {
        "account_count": int(account_count),
        "live_now": int(live_now),
        "session_total": int(session_total),
        "sample_total": int(sample_total),
        "offline_count": int(offline_count),
        "unknown_count": int(unknown_count),
        "stale_count": int(stale_count),
        "removed_total": int(removed_total),
        "last_probe_at": probe["finished_at"] if probe and probe["finished_at"] else None,
        "last_probe_live": int(probe["live_found"]) if probe and probe["live_found"] is not None else 0,
        "last_audit_at": audit["finished_at"] if audit and audit["finished_at"] else None,
        "last_audit_removed": int(audit["removed_count"]) if audit and audit["removed_count"] is not None else 0,
    }


def last_audit_run(db_path: Path) -> Optional[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(
            """
            SELECT id, started_at, finished_at, accounts_checked, removed_count, error_count
            FROM audit_runs
            WHERE finished_at IS NOT NULL
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()


def start_audit_run(db_path: Path) -> int:
    ts = now_iso()
    with connect(db_path) as conn:
        conn.execute("INSERT INTO audit_runs (started_at) VALUES (?)", (ts,))
        return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def finish_audit_run(
    db_path: Path,
    run_id: int,
    accounts_checked: int,
    removed_count: int,
    error_count: int,
) -> None:
    ts = now_iso()
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE audit_runs
            SET finished_at=?, accounts_checked=?, removed_count=?, error_count=?
            WHERE id=?
            """,
            (ts, accounts_checked, removed_count, error_count, run_id),
        )


def count_removed_accounts(db_path: Path) -> int:
    with connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM removed_accounts").fetchone()[0])


def list_removed_accounts(db_path: Path, *, group: Optional[str] = None, limit: int = 200) -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        if group:
            return conn.execute(
                """
                SELECT id, username, display_name, profile_url, account_group, reason, status_code, detail, removed_at
                FROM removed_accounts
                WHERE account_group = ?
                ORDER BY removed_at DESC
                LIMIT ?
                """,
                (group, limit),
            ).fetchall()
        return conn.execute(
            """
            SELECT id, username, display_name, profile_url, account_group, reason, status_code, detail, removed_at
            FROM removed_accounts
            ORDER BY removed_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def record_removed_account(
    db_path: Path,
    *,
    audit_run_id: int,
    username: str,
    display_name: Optional[str],
    profile_url: Optional[str],
    account_group: str = "own",
    reason: str,
    status_code: Optional[int],
    detail: Optional[str],
) -> None:
    ts = now_iso()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO removed_accounts
            (audit_run_id, username, display_name, profile_url, account_group, reason, status_code, detail, removed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_run_id,
                username,
                display_name,
                profile_url,
                account_group,
                reason,
                status_code,
                detail,
                ts,
            ),
        )


def disable_account_and_close_sessions(db_path: Path, username: str) -> None:
    ts = now_iso()
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM accounts WHERE lower(username)=lower(?)",
            (username,),
        ).fetchone()
        if not row:
            return
        account_id = int(row["id"])
        conn.execute(
            "UPDATE accounts SET enabled=0, updated_at=? WHERE id=?",
            (ts, account_id),
        )
        conn.execute(
            """
            UPDATE live_sessions
            SET status='ended', ended_at=?, miss_streak=0
            WHERE account_id=? AND status='live'
            """,
            (ts, account_id),
        )
