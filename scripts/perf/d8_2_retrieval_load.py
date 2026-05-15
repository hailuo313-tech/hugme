#!/usr/bin/env python3
"""D8-2 memory retrieval load probe.

This is a small standard-library probe for the read-only retrieval endpoint:

    POST /api/v1/users/{user_id}/memories/retrieve

It reports client-side latency percentiles plus the app-reported `latency_ms`
field. Keep it outside CI; it is for staging/production smoke evidence after a
release owner chooses a safe beta user with existing memories.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


BASE_URL = os.environ.get("ERIS_BASE_URL", "https://hugme2.com").rstrip("/")
USER_ID = os.environ.get("ERIS_USER_ID", "")
REQUESTS = int(os.environ.get("D8_2_REQUESTS", "30"))
CONCURRENCY = int(os.environ.get("D8_2_CONCURRENCY", "1"))
TIMEOUT_SECONDS = float(os.environ.get("D8_2_TIMEOUT_SECONDS", "20"))
QUERY = os.environ.get("D8_2_QUERY", "performance smoke memory retrieval")


@dataclass
class ProbeResult:
    ok: bool
    status: int | None
    client_ms: float
    app_ms: float | None
    embedding_used: bool | None
    fallback_reason: str | None
    candidates_scanned: int | None
    error: str | None


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = int((len(ordered) - 1) * pct)
    return ordered[idx]


def one_request() -> ProbeResult:
    url = f"{BASE_URL}/api/v1/users/{USER_ID}/memories/retrieve"
    payload = {
        "query": QUERY,
        "k": 10,
        "k_candidates": 30,
        "min_importance": 0,
        "include_global": True,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8")
            data: dict[str, Any] = json.loads(raw)
            elapsed = (time.perf_counter() - started) * 1000
            return ProbeResult(
                ok=200 <= resp.status < 300,
                status=resp.status,
                client_ms=elapsed,
                app_ms=float(data.get("latency_ms")) if data.get("latency_ms") is not None else None,
                embedding_used=bool(data.get("embedding_used")),
                fallback_reason=data.get("fallback_reason"),
                candidates_scanned=data.get("candidates_scanned"),
                error=None,
            )
    except urllib.error.HTTPError as exc:
        elapsed = (time.perf_counter() - started) * 1000
        return ProbeResult(
            ok=False,
            status=exc.code,
            client_ms=elapsed,
            app_ms=None,
            embedding_used=None,
            fallback_reason=None,
            candidates_scanned=None,
            error=f"HTTPError:{exc.code}",
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1000
        return ProbeResult(
            ok=False,
            status=None,
            client_ms=elapsed,
            app_ms=None,
            embedding_used=None,
            fallback_reason=None,
            candidates_scanned=None,
            error=f"{type(exc).__name__}:{exc}",
        )


def summarize(results: list[ProbeResult]) -> dict[str, Any]:
    client = [r.client_ms for r in results]
    app = [r.app_ms for r in results if r.app_ms is not None]
    errors = [r.error for r in results if r.error]
    return {
        "base_url": BASE_URL,
        "requests": REQUESTS,
        "concurrency": CONCURRENCY,
        "success": sum(1 for r in results if r.ok),
        "client_ms": {
            "min": round(min(client), 1) if client else None,
            "p50": round(percentile(client, 0.50) or 0, 1),
            "p95": round(percentile(client, 0.95) or 0, 1),
            "p99": round(percentile(client, 0.99) or 0, 1),
            "max": round(max(client), 1) if client else None,
            "mean": round(statistics.fmean(client), 1) if client else None,
        },
        "app_latency_ms": {
            "p95": round(percentile(app, 0.95) or 0, 1) if app else None,
            "max": round(max(app), 1) if app else None,
        },
        "embedding_used_values": sorted({r.embedding_used for r in results if r.embedding_used is not None}),
        "fallback_reasons": sorted({r.fallback_reason for r in results if r.fallback_reason}),
        "candidates_scanned_values": sorted({r.candidates_scanned for r in results if r.candidates_scanned is not None}),
        "errors": errors[:5],
    }


def main() -> int:
    if not USER_ID:
        print("Set ERIS_USER_ID to a safe beta user with existing memories.", flush=True)
        return 2
    workers = max(1, min(CONCURRENCY, REQUESTS))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda _: one_request(), range(REQUESTS)))
    print(json.dumps(summarize(results), indent=2, ensure_ascii=False))
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
