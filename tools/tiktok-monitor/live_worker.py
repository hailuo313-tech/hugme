"""Run live probe / sample jobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from accounts_store import delete_account, list_accounts as list_config_accounts
from account_health import REASON_ERROR, check_account_health
from live_db import (
    account_verification_state,
    apply_probe_result,
    cancel_stale_probe_runs,
    cleanup_stale_jobs,
    count_managed_live_accounts,
    disable_account_and_close_sessions,
    finish_audit_run,
    finish_probe_run,
    init_db,
    list_active_sessions,
    managed_recheck_interval_minutes,
    record_local_probe,
    record_managed_probe,
    record_removed_account,
    reserve_managed_budget,
    start_audit_run,
    start_probe_run,
    sync_accounts,
    update_probe_progress,
)
from live_fetch import LiveStatus, fetch_live_status
from managed_live import ManagedLiveStatus, fetch_managed_statuses, managed_api_enabled
from job_lock import cleanup_stale_lock, job_lock

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
DB_PATH = ROOT / "data" / "tiktok_live.sqlite"


def load_settings() -> dict:
    if not CONFIG_PATH.exists():
        return {
            "probe_delay_sec": 0.8,
            "offline_miss_threshold": 2,
            "probe_workers": 8,
            "probe_retries": 1,
            "probe_jitter_sec": 0.35,
            "secondary_confirmation_delay_sec": 2.0,
            "audit_delay_sec": 1.0,
            "live_api": {"enabled": False},
        }
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    monitor = data.get("live_monitor") if isinstance(data.get("live_monitor"), dict) else {}
    audit = data.get("account_audit") if isinstance(data.get("account_audit"), dict) else {}
    live_api = data.get("live_api") if isinstance(data.get("live_api"), dict) else {}
    return {
        "probe_delay_sec": float(monitor.get("probe_delay_sec") or 0.5),
        "probe_timeout_sec": float(monitor.get("probe_timeout_sec") or 10.0),
        "offline_miss_threshold": int(monitor.get("offline_miss_threshold") or 2),
        "probe_workers": max(1, min(16, int(monitor.get("probe_workers") or 8))),
        "probe_retries": max(0, min(3, int(monitor.get("probe_retries") or 1))),
        "probe_jitter_sec": max(0.0, float(monitor.get("probe_jitter_sec") or 0.35)),
        "secondary_confirmation_delay_sec": max(
            0.0, min(10.0, float(monitor.get("secondary_confirmation_delay_sec") or 2.0))
        ),
        "audit_delay_sec": float(audit.get("delay_sec") or 1.0),
        "live_api": live_api,
    }


def _fetch_account_status(acc, *, timeout: float, retries: int, jitter: float):
    if jitter > 0:
        time.sleep(random.uniform(0, jitter))
    return fetch_live_status(acc.username, timeout=timeout, retries=retries)


def _consensus_status(
    local: LiveStatus,
    managed: Optional[ManagedLiveStatus],
    *,
    managed_required: bool,
) -> LiveStatus:
    if not managed_required:
        return local

    managed_outcome = managed.outcome if managed else "unknown"
    local_outcome = local.outcome
    managed_source = managed.source if managed else "managed:missing"
    source = f"{managed_source}+local:{local.source}"
    if local_outcome == managed_outcome and local_outcome in {"live", "offline"}:
        is_live = local_outcome == "live"
        return LiveStatus(
            username=local.username,
            is_live=is_live,
            room_id=local.room_id or (managed.room_id if managed else None),
            title=local.title or (managed.title if managed else None),
            viewer_count=local.viewer_count
            if local.viewer_count is not None
            else (managed.viewer_count if managed else None),
            enter_count=local.enter_count,
            source=source,
        )

    details = [
        f"managed={managed_outcome}",
        f"local={local_outcome}",
    ]
    if managed and managed.error:
        details.append(managed.error)
    if local.error:
        details.append(local.error)
    return LiveStatus(
        username=local.username,
        is_live=False,
        room_id=local.room_id or (managed.room_id if managed else None),
        title=local.title or (managed.title if managed else None),
        viewer_count=None,
        source=source,
        error="pending confirmation: " + "; ".join(details),
    )


def _confirm_live_candidate(
    local: LiveStatus,
    managed_statuses: dict[str, ManagedLiveStatus],
    *,
    managed_required: bool,
) -> LiveStatus:
    if not managed_required or local.outcome != "live":
        return local
    return _consensus_status(
        local,
        managed_statuses.get(local.username.casefold()),
        managed_required=True,
    )


def _managed_due(last_probe_at: Optional[str], interval_minutes: int) -> bool:
    if not last_probe_at:
        return True
    try:
        checked_at = datetime.fromisoformat(last_probe_at)
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return True
    elapsed = (datetime.now(timezone.utc) - checked_at).total_seconds()
    return elapsed >= interval_minutes * 60


def _pending(local: LiveStatus, message: str) -> LiveStatus:
    return LiveStatus(
        username=local.username,
        is_live=False,
        room_id=local.room_id,
        title=local.title,
        source=f"local:{local.source}",
        error=f"pending confirmation: {message}",
    )


def _staggered_cache_minutes(username: str, *, has_room_id: bool) -> int:
    digest = hashlib.sha256(username.casefold().encode("utf-8")).digest()
    offset = int.from_bytes(digest[:2], "big")
    if has_room_id:
        return 720 + (offset % 361)
    return 240 + (offset % 241)


def _managed_cache_fresh(state, local: LiveStatus) -> bool:
    if not state or not state["last_managed_probe_at"]:
        return False
    current_room = str(local.room_id or "").strip()
    checked_room = str(state["last_managed_room_id"] or "").strip()
    if current_room and checked_room and current_room != checked_room:
        return False
    status = str(state["last_managed_status"] or "")
    if status == "offline":
        ttl = _staggered_cache_minutes(
            local.username,
            has_room_id=bool(current_room),
        )
    elif status == "unknown":
        ttl = 120
    else:
        return False
    return not _managed_due(state["last_managed_probe_at"], ttl)


def _managed_primary_result(
    local: LiveStatus,
    managed: ManagedLiveStatus,
) -> LiveStatus:
    # A managed provider is an independent signal, not an authority that may
    # overwrite a contradictory local Webcast/playback result.  In particular,
    # some providers return false negatives for region-restricted live rooms.
    # Preserve the strict contract: only matching signals are conclusive.
    return _consensus_status(
        local,
        managed,
        managed_required=True,
    )


def _fetch_budgeted_managed(
    *,
    usernames: list[str],
    category: str,
    live_api: dict,
    local_results: dict[str, LiveStatus],
) -> dict[str, ManagedLiveStatus]:
    ordered = sorted(set(usernames), key=str.casefold)
    allowed = reserve_managed_budget(DB_PATH, len(ordered), category=category)
    selected = ordered[:allowed]
    results = fetch_managed_statuses(selected, live_api) if selected else {}
    for username in selected:
        status = results.get(username.casefold())
        if status is None:
            status = ManagedLiveStatus(
                username=username,
                outcome="unknown",
                source="managed:missing",
                error="managed API returned no result",
            )
            results[username.casefold()] = status
        record_managed_probe(
            DB_PATH,
            username,
            outcome=status.outcome,
            error=status.error,
            room_id=(
                status.room_id
                or local_results.get(username.casefold(), LiveStatus(username, False)).room_id
            ),
        )
    return results


def _apply_budgeted_consensus(
    local_results: dict[str, LiveStatus],
    *,
    live_api: dict,
    managed_required: bool,
) -> dict[str, LiveStatus]:
    if not managed_required:
        return dict(local_results)

    pending_results: dict[str, LiveStatus] = {}
    active_candidates: list[str] = []
    new_candidates: list[str] = []
    active_count = count_managed_live_accounts(DB_PATH)
    recheck_minutes = managed_recheck_interval_minutes(active_count)

    for key, local in local_results.items():
        live_streak, offline_streak = record_local_probe(DB_PATH, local.username, local.outcome)
        state = account_verification_state(DB_PATH, local.username)
        confirmed_live = bool(
            state
            and state["last_probe_status"] == "live"
            and state["last_managed_status"] == "live"
        )

        if confirmed_live:
            if _managed_due(state["last_managed_probe_at"], recheck_minutes):
                active_candidates.append(local.username)
            else:
                cached = ManagedLiveStatus(
                    username=local.username,
                    outcome="live",
                    source="managed:cached",
                )
                pending_results[key] = _managed_primary_result(
                    local,
                    cached,
                )
        elif local.outcome == "unknown":
            if _managed_cache_fresh(state, local):
                cached_status = ManagedLiveStatus(
                    username=local.username,
                    outcome=state["last_managed_status"],
                    source="managed:cached",
                )
                pending_results[key] = _managed_primary_result(local, cached_status)
            else:
                active_candidates.append(local.username)
        elif local.outcome == "live":
            if live_streak >= 2:
                new_candidates.append(local.username)
            else:
                pending_results[key] = _pending(
                    local, "waiting for second consecutive local live signal"
                )
        elif confirmed_live:
            if offline_streak >= 2:
                new_candidates.append(local.username)
            else:
                pending_results[key] = _pending(
                    local, "waiting for second consecutive local offline signal"
                )
        else:
            pending_results[key] = local

    managed_statuses = _fetch_budgeted_managed(
        usernames=active_candidates,
        category="active",
        live_api=live_api,
        local_results=local_results,
    )
    managed_statuses.update(
        _fetch_budgeted_managed(
            usernames=new_candidates,
            category="active",
            live_api=live_api,
            local_results=local_results,
        )
    )

    for username in active_candidates + new_candidates:
        key = username.casefold()
        local = local_results[key]
        managed = managed_statuses.get(key)
        if managed is None:
            pending_results[key] = _pending(local, "daily Apify budget exhausted")
        else:
            pending_results[key] = _managed_primary_result(local, managed)
    return pending_results


def cmd_probe() -> int:
    with job_lock(ROOT, "probe") as acquired:
        if not acquired:
            print("[probe] already running, skip")
            return 0

        settings = load_settings()
        init_db(DB_PATH)
        cleanup_stale_jobs(DB_PATH)
        cleanup_stale_lock(ROOT, "probe")
        cancel_stale_probe_runs(DB_PATH)
        sync_accounts(DB_PATH, list_config_accounts(CONFIG_PATH))
        accounts = list_config_accounts(CONFIG_PATH)
        run_id = start_probe_run(DB_PATH)
        live_found = 0
        errors = 0
        probe_timeout = float(settings.get("probe_timeout_sec") or 10.0)
        workers = int(settings["probe_workers"])
        retries = int(settings["probe_retries"])
        jitter = float(settings["probe_jitter_sec"])
        checked = 0
        live_api = settings["live_api"]
        require_managed = managed_api_enabled(live_api)
        local_results: dict[str, LiveStatus] = {}

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tiktok-probe") as executor:
            futures = {
                executor.submit(
                    _fetch_account_status,
                    acc,
                    timeout=probe_timeout,
                    retries=retries,
                    jitter=jitter,
                ): acc
                for acc in accounts
            }
            for future in as_completed(futures):
                acc = futures[future]
                checked += 1
                try:
                    local_results[acc.username.casefold()] = future.result()
                except Exception as exc:
                    print(f"[probe] @{acc.username} error: {exc}")
                    local_results[acc.username.casefold()] = LiveStatus(
                        username=acc.username,
                        is_live=False,
                        source="worker",
                        error=str(exc),
                    )
                update_probe_progress(DB_PATH, run_id, checked, live_found, errors)

        secondary_accounts = []
        if require_managed:
            for acc in accounts:
                local = local_results[acc.username.casefold()]
                state = account_verification_state(DB_PATH, acc.username)
                was_confirmed_live = bool(
                    state
                    and state["last_probe_status"] == "live"
                    and state["last_managed_status"] == "live"
                )
                if local.outcome == "live" or (
                    local.outcome == "offline" and was_confirmed_live
                ):
                    record_local_probe(DB_PATH, acc.username, local.outcome)
                    secondary_accounts.append(acc)

        if secondary_accounts:
            delay = float(settings["secondary_confirmation_delay_sec"])
            if delay > 0:
                time.sleep(delay)
            with ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="tiktok-confirm",
            ) as executor:
                futures = {
                    executor.submit(
                        _fetch_account_status,
                        acc,
                        timeout=probe_timeout,
                        retries=retries,
                        jitter=jitter,
                    ): acc
                    for acc in secondary_accounts
                }
                for future in as_completed(futures):
                    acc = futures[future]
                    try:
                        local_results[acc.username.casefold()] = future.result()
                    except Exception as exc:
                        local_results[acc.username.casefold()] = LiveStatus(
                            username=acc.username,
                            is_live=False,
                            source="worker-confirm",
                            error=str(exc),
                        )

        final_results = _apply_budgeted_consensus(
            local_results,
            live_api=live_api,
            managed_required=require_managed,
        )
        checked = 0
        for acc in accounts:
            checked += 1
            result = final_results[acc.username.casefold()]
            if result.error:
                errors += 1
                print(f"[probe] UNKNOWN @{acc.username}: {result.error}")
            elif result.is_live:
                live_found += 1
                print(
                    f"[probe] LIVE @{acc.username} room={result.room_id} "
                    f"viewers={result.viewer_count} source={result.source}"
                )
            else:
                print(f"[probe] offline @{acc.username} source={result.source}")

            apply_probe_result(
                DB_PATH,
                username=acc.username,
                is_live=result.is_live,
                room_id=result.room_id,
                title=result.title,
                viewer_count=result.viewer_count,
                enter_count=result.enter_count,
                miss_threshold=settings["offline_miss_threshold"],
                source=result.source,
                error=result.error,
            )
            update_probe_progress(DB_PATH, run_id, checked, live_found, errors)

        finish_probe_run(DB_PATH, run_id, len(accounts), live_found, errors)
        print(f"[probe] done accounts={len(accounts)} live={live_found} errors={errors}")
        return 0


def cmd_sample() -> int:
    settings = load_settings()
    init_db(DB_PATH)
    sessions = list_active_sessions(DB_PATH)
    if not sessions:
        print("[sample] no active live sessions")
        return 0

    confirmed_live = 0
    unknown = 0
    workers = int(settings["probe_workers"])
    timeout = float(settings.get("probe_timeout_sec") or 10.0)
    retries = int(settings["probe_retries"])
    live_api = settings["live_api"]
    require_managed = managed_api_enabled(live_api)
    local_results: dict[str, LiveStatus] = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tiktok-live-recheck") as executor:
        futures = {
            executor.submit(
                fetch_live_status,
                row["username"],
                timeout,
                retries,
            ): row
            for row in sessions
        }
        for future in as_completed(futures):
            row = futures[future]
            try:
                local_results[str(row["username"]).casefold()] = future.result()
            except Exception as exc:
                local_results[str(row["username"]).casefold()] = LiveStatus(
                    username=row["username"],
                    is_live=False,
                    room_id=row["room_id"],
                    title=row["title"],
                    source="sample",
                    error=str(exc),
                )

    for row in sessions:
        local = local_results[str(row["username"]).casefold()]
        record_local_probe(DB_PATH, local.username, local.outcome)
        state = account_verification_state(DB_PATH, local.username)
        if not require_managed:
            result = local
        elif (
            local.outcome == "live"
            and state
            and state["last_managed_status"] == "live"
        ):
            result = LiveStatus(
                username=local.username,
                is_live=True,
                room_id=local.room_id,
                title=local.title,
                viewer_count=local.viewer_count,
                enter_count=local.enter_count,
                source=f"managed:cached+local:{local.source}",
            )
        else:
            result = _pending(local, "waiting for the next budgeted full confirmation")
        error = result.error

        if error:
            unknown += 1
            apply_probe_result(
                DB_PATH,
                username=row["username"],
                is_live=False,
                room_id=row["room_id"],
                title=row["title"],
                viewer_count=None,
                miss_threshold=settings["offline_miss_threshold"],
                source=result.source,
                error=error,
            )
            print(f"[sample] UNKNOWN @{row['username']}: {error}")
            continue

        apply_probe_result(
            DB_PATH,
            username=row["username"],
            is_live=result.is_live,
            room_id=result.room_id or row["room_id"],
            title=result.title or row["title"],
            viewer_count=result.viewer_count,
            enter_count=result.enter_count,
            miss_threshold=settings["offline_miss_threshold"],
            source=result.source,
        )
        if result.is_live:
            confirmed_live += 1
            print(
                f"[sample] LIVE @{row['username']} viewers={result.viewer_count} "
                f"enter={result.enter_count}"
            )
        else:
            print(f"[sample] offline miss @{row['username']}")

    print(
        f"[sample] done sessions={len(sessions)} "
        f"confirmed_live={confirmed_live} unknown={unknown}"
    )
    return 0


def cmd_audit() -> int:
    with job_lock(ROOT, "audit") as acquired:
        if not acquired:
            print("[audit] already running, skip")
            return 0

        settings = load_settings()
        init_db(DB_PATH)
        sync_accounts(DB_PATH, list_config_accounts(CONFIG_PATH))
        accounts = list_config_accounts(CONFIG_PATH)
        run_id = start_audit_run(DB_PATH)
        removed = 0
        errors = 0

        for acc in accounts:
            health = check_account_health(acc.username)
            if health.reason == REASON_ERROR:
                errors += 1
                print(f"[audit] @{acc.username} skip (network): {health.detail}")
                time.sleep(settings["audit_delay_sec"])
                continue

            if health.ok:
                print(f"[audit] @{acc.username} ok")
                time.sleep(settings["audit_delay_sec"])
                continue

            deleted = delete_account(CONFIG_PATH, acc.username)
            disable_account_and_close_sessions(DB_PATH, acc.username)
            record_removed_account(
                DB_PATH,
                audit_run_id=run_id,
                username=acc.username,
                display_name=health.display_name or acc.name,
                profile_url=health.profile_url or acc.url,
                account_group=acc.group,
                reason=health.reason,
                status_code=health.status_code,
                detail=health.detail,
            )
            removed += 1
            print(f"[audit] REMOVED @{acc.username} reason={health.reason} detail={health.detail}")

            time.sleep(settings["audit_delay_sec"])

        finish_audit_run(DB_PATH, run_id, len(accounts), removed, errors)
        print(f"[audit] done checked={len(accounts)} removed={removed} errors={errors}")
        return 0 if errors == 0 else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="TikTok live monitor worker")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe", help="check all accounts for live status")
    sub.add_parser("sample", help="sample viewer counts for active sessions")
    sub.add_parser("audit", help="daily audit: remove banned/unavailable accounts")
    args = parser.parse_args(argv)

    if args.cmd == "probe":
        return cmd_probe()
    if args.cmd == "sample":
        return cmd_sample()
    if args.cmd == "audit":
        return cmd_audit()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
