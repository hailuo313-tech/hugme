#!/usr/bin/env python3
"""ERIS NEWS page server: static UI + fetch/status API on /news/*."""

from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(os.environ.get("NEWS_BASE_DIR", Path(__file__).resolve().parent))
PUBLIC_DIR = BASE_DIR / "public"
OUTPUT_DIR = BASE_DIR / "output"
DB_PATH = BASE_DIR / "data" / "news_history.db"
RULES_PATH = PUBLIC_DIR / "global_intel_rules.json"
FETCH_SCRIPT = BASE_DIR / "global_intel_news.py"

from news_db import get_latest_run, get_run, import_output_dir, init_db, list_runs
HOST = os.environ.get("NEWS_HOST", "127.0.0.1")
PORT = int(os.environ.get("NEWS_PORT", "8765"))
PYTHON_BIN = os.environ.get("PYTHON_BIN", "python3")
FETCH_TIMEOUT_SECONDS = int(os.environ.get("NEWS_FETCH_TIMEOUT_SECONDS", "180"))

_state_lock = threading.Lock()
_state: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "status": "idle",
    "message": "",
    "latest_json": None,
    "latest_markdown": None,
    "returncode": None,
    "history": [],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _latest_output_files() -> tuple[Path | None, Path | None]:
    if not OUTPUT_DIR.exists():
        return None, None
    json_files = sorted(OUTPUT_DIR.glob("global_intel_*.json"), reverse=True)
    if not json_files:
        return None, None
    latest_json = json_files[0]
    latest_md = latest_json.with_suffix(".md")
    if not latest_md.exists():
        latest_md = None
    return latest_json, latest_md


def _refresh_latest_fields() -> None:
    latest_json, latest_md = _latest_output_files()
    _state["latest_json"] = latest_json.name if latest_json else None
    _state["latest_markdown"] = latest_md.name if latest_md else None


def _run_fetch(allow_partial: bool) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        PYTHON_BIN,
        str(FETCH_SCRIPT),
        "--output-dir",
        str(OUTPUT_DIR),
    ]
    if allow_partial:
        cmd.append("--allow-partial")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=FETCH_TIMEOUT_SECONDS,
            check=False,
        )
        message = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        with _state_lock:
            _state["running"] = False
            _state["finished_at"] = _now_iso()
            _state["returncode"] = proc.returncode
            _state["message"] = message
            _refresh_latest_fields()
            if proc.returncode == 0:
                _state["status"] = "success"
            else:
                _state["status"] = "error"
    except subprocess.TimeoutExpired:
        with _state_lock:
            _state["running"] = False
            _state["finished_at"] = _now_iso()
            _state["status"] = "error"
            _state["returncode"] = 124
            _state["message"] = "抓取超时：180 秒内没有完成。"
    except Exception as exc:
        with _state_lock:
            _state["running"] = False
            _state["finished_at"] = _now_iso()
            _state["status"] = "error"
            _state["returncode"] = 1
            _state["message"] = str(exc)


class NewsHandler(BaseHTTPRequestHandler):
    server_version = "ERISNews/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, content_type: str, status: int = 200) -> None:
        self._send_bytes(text.encode("utf-8"), content_type, status)

    def _route_path(self) -> str:
        parsed = urlparse(self.path)
        path = parsed.path or "/"
        if path == "/news":
            path = "/news/"
        return path

    def _query(self) -> dict[str, list[str]]:
        return parse_qs(urlparse(self.path).query)

    def do_GET(self) -> None:
        path = self._route_path()
        if path in {"/news/", "/news/index.html"}:
            index = PUBLIC_DIR / "index.html"
            if not index.exists():
                self.send_error(404, "index.html not found")
                return
            self._send_text(index.read_text(encoding="utf-8"), "text/html; charset=utf-8")
            return
        if path == "/news/api/status":
            with _state_lock:
                self._send_json(dict(_state))
            return
        if path == "/news/api/history":
            self._send_json({"runs": list_runs(db_path=DB_PATH)})
            return
        if path.startswith("/news/api/runs/"):
            run_id_raw = path[len("/news/api/runs/") :].strip("/")
            try:
                run_id = int(run_id_raw)
            except ValueError:
                self._send_json({"error": "invalid run id"}, status=400)
                return
            run = get_run(run_id, db_path=DB_PATH)
            if not run:
                self._send_json({"error": "run not found"}, status=404)
                return
            self._send_json(run)
            return
        if path == "/news/api/latest":
            run = get_latest_run(db_path=DB_PATH)
            if run:
                self._send_json(run)
                return
            latest_json, _ = _latest_output_files()
            if not latest_json:
                self._send_json({"error": "no output yet"}, status=404)
                return
            self._send_json(json.loads(latest_json.read_text(encoding="utf-8")))
            return
        if path == "/news/public/global_intel_rules.json":
            if not RULES_PATH.exists():
                self.send_error(404, "rules not found")
                return
            self._send_text(
                RULES_PATH.read_text(encoding="utf-8"),
                "application/json; charset=utf-8",
            )
            return
        if path.startswith("/news/public/"):
            rel = path[len("/news/public/") :]
            target = (PUBLIC_DIR / rel).resolve()
            if PUBLIC_DIR.resolve() not in target.parents and target != PUBLIC_DIR.resolve():
                self.send_error(403, "forbidden")
                return
            if not target.exists() or not target.is_file():
                self.send_error(404, "not found")
                return
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self._send_bytes(target.read_bytes(), content_type)
            return
        self.send_error(404, "Not Found")

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        path = self._route_path()
        if path == "/news/api/fetch":
            query = self._query()
            allow_partial = "allow_partial" in query
            with _state_lock:
                if _state.get("running"):
                    self._send_json({"error": "fetch already running"}, status=409)
                    return
                _state.update(
                    {
                        "running": True,
                        "started_at": _now_iso(),
                        "finished_at": None,
                        "status": "fetching",
                        "message": "正在抓取海外 RSS/Atom 新闻源...",
                        "returncode": None,
                    }
                )
            thread = threading.Thread(target=_run_fetch, args=(allow_partial,), daemon=True)
            thread.start()
            self._send_json({"accepted": True, "allow_partial": allow_partial}, status=202)
            return
        self.send_error(404, "Not Found")


def main() -> None:
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    init_db(DB_PATH)
    imported = import_output_dir(OUTPUT_DIR, db_path=DB_PATH)
    if imported:
        print(f"Imported {imported} historical fetch run(s) into {DB_PATH}")
    _refresh_latest_fields()
    server = ThreadingHTTPServer((HOST, PORT), NewsHandler)
    print(f"ERIS NEWS listening on http://{HOST}:{PORT}/news/")
    server.serve_forever()


if __name__ == "__main__":
    main()
