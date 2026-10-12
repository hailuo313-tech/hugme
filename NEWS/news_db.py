#!/usr/bin/env python3
"""SQLite storage for global intel fetch runs and items."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "news_history.db"
_RUN_KEY_RE = re.compile(r"^global_intel_\d{8}_\d{6}$")

_lock = threading.Lock()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    with _lock:
        conn = _connect(db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS fetch_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_key TEXT NOT NULL UNIQUE,
                    generated_at TEXT NOT NULL,
                    target_total INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    deficits_json TEXT NOT NULL DEFAULT '{}',
                    json_path TEXT,
                    markdown_path TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_fetch_runs_generated_at
                    ON fetch_runs(generated_at DESC);

                CREATE TABLE IF NOT EXISTS fetch_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES fetch_runs(id) ON DELETE CASCADE,
                    item_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    region TEXT,
                    subcategory TEXT,
                    title TEXT NOT NULL,
                    summary TEXT,
                    url TEXT NOT NULL,
                    source TEXT,
                    published_at TEXT,
                    age_hours REAL,
                    sort_order INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_fetch_items_run_id ON fetch_items(run_id);
                """
            )
            conn.commit()
        finally:
            conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_fetch(
    payload: dict[str, Any],
    *,
    run_key: str,
    json_path: str | None = None,
    markdown_path: str | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    init_db(db_path)
    items = payload.get("items") or []
    deficits = payload.get("deficits") or {}
    with _lock:
        conn = _connect(db_path)
        try:
            cur = conn.execute(
                """
                INSERT INTO fetch_runs (
                    run_key, generated_at, target_total, total,
                    deficits_json, json_path, markdown_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_key) DO UPDATE SET
                    generated_at = excluded.generated_at,
                    target_total = excluded.target_total,
                    total = excluded.total,
                    deficits_json = excluded.deficits_json,
                    json_path = excluded.json_path,
                    markdown_path = excluded.markdown_path
                """,
                (
                    run_key,
                    str(payload.get("generated_at") or _now_iso()),
                    int(payload.get("target_total") or 0),
                    int(payload.get("total") or len(items)),
                    json.dumps(deficits, ensure_ascii=False),
                    json_path,
                    markdown_path,
                    _now_iso(),
                ),
            )
            run_id = conn.execute(
                "SELECT id FROM fetch_runs WHERE run_key = ?",
                (run_key,),
            ).fetchone()["id"]
            conn.execute("DELETE FROM fetch_items WHERE run_id = ?", (run_id,))
            for idx, item in enumerate(items):
                conn.execute(
                    """
                    INSERT INTO fetch_items (
                        run_id, item_id, category, region, subcategory,
                        title, summary, url, source, published_at, age_hours, sort_order
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        str(item.get("id") or ""),
                        str(item.get("category") or ""),
                        item.get("region"),
                        item.get("subcategory"),
                        str(item.get("title") or ""),
                        item.get("summary"),
                        str(item.get("url") or ""),
                        item.get("source"),
                        item.get("published_at"),
                        item.get("age_hours"),
                        idx,
                    ),
                )
            conn.commit()
            return int(run_id)
        finally:
            conn.close()


def list_runs(*, limit: int = 100, db_path: Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    init_db(db_path)
    with _lock:
        conn = _connect(db_path)
        try:
            rows = conn.execute(
                """
                SELECT id, run_key, generated_at, target_total, total, deficits_json
                FROM fetch_runs
                ORDER BY generated_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "run_key": row["run_key"],
                    "generated_at": row["generated_at"],
                    "target_total": row["target_total"],
                    "total": row["total"],
                    "deficits": json.loads(row["deficits_json"] or "{}"),
                }
                for row in rows
            ]
        finally:
            conn.close()


def get_run(run_id: int, *, db_path: Path = DEFAULT_DB_PATH) -> dict[str, Any] | None:
    init_db(db_path)
    with _lock:
        conn = _connect(db_path)
        try:
            row = conn.execute(
                """
                SELECT id, run_key, generated_at, target_total, total, deficits_json
                FROM fetch_runs WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
            if not row:
                return None
            items = conn.execute(
                """
                SELECT item_id AS id, category, region, subcategory, title, summary,
                       url, source, published_at, age_hours
                FROM fetch_items
                WHERE run_id = ?
                ORDER BY sort_order ASC, id ASC
                """,
                (run_id,),
            ).fetchall()
            normalized_items = []
            for item in items:
                row_data = dict(item)
                row_data["sector"] = row_data.get("category")
                normalized_items.append(row_data)
            return {
                "id": row["id"],
                "run_key": row["run_key"],
                "generated_at": row["generated_at"],
                "target_total": row["target_total"],
                "total": row["total"],
                "deficits": json.loads(row["deficits_json"] or "{}"),
                "items": normalized_items,
            }
        finally:
            conn.close()


def get_latest_run(*, db_path: Path = DEFAULT_DB_PATH) -> dict[str, Any] | None:
    runs = list_runs(limit=1, db_path=db_path)
    if not runs:
        return None
    return get_run(runs[0]["id"], db_path=db_path)


def import_json_file(
    json_path: Path,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> int | None:
    if not json_path.exists() or json_path.suffix != ".json":
        return None
    run_key = json_path.stem
    if not _RUN_KEY_RE.match(run_key):
        return None
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    md_path = json_path.with_suffix(".md")
    return save_fetch(
        payload,
        run_key=run_key,
        json_path=str(json_path),
        markdown_path=str(md_path) if md_path.exists() else None,
        db_path=db_path,
    )


def import_output_dir(
    output_dir: Path,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    if not output_dir.exists():
        return 0
    imported = 0
    for json_path in sorted(output_dir.glob("global_intel_*.json")):
        try:
            if import_json_file(json_path, db_path=db_path) is not None:
                imported += 1
        except (OSError, json.JSONDecodeError, sqlite3.Error):
            continue
    return imported
