"""Managed LIVE API adapter used as the primary status signal."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

import requests


@dataclass
class ManagedLiveStatus:
    username: str
    outcome: str
    room_id: Optional[str] = None
    title: Optional[str] = None
    viewer_count: Optional[int] = None
    source: str = "managed"
    error: Optional[str] = None


def managed_api_enabled(config: dict) -> bool:
    env_value = os.getenv("TIKTOK_LIVE_API_ENABLED")
    if env_value is not None:
        return env_value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(config.get("enabled"))


def _clean_username(value: Any) -> str:
    return str(value or "").strip().lstrip("@")


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


def _outcome(item: dict) -> Optional[str]:
    for key in ("is_live", "isLive", "live", "is_live_now"):
        value = item.get(key)
        if isinstance(value, bool):
            return "live" if value else "offline"
        if value in (0, 1, "0", "1"):
            return "live" if str(value) == "1" else "offline"
    raw = str(
        item.get("status")
        or item.get("live_status")
        or item.get("liveStatus")
        or item.get("state")
        or ""
    ).strip().lower()
    if raw in {"live", "online", "broadcasting", "on_air"}:
        return "live"
    if raw in {"offline", "ended", "not_live", "not-live"}:
        return "offline"
    return None


def _username_from_item(item: dict) -> str:
    user = item.get("user") if isinstance(item.get("user"), dict) else {}
    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    return _clean_username(
        item.get("username")
        or item.get("handle")
        or item.get("unique_id")
        or item.get("uniqueId")
        or user.get("uniqueId")
        or user.get("unique_id")
        or author.get("uniqueId")
        or author.get("unique_id")
    )


def _items(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "items", "results", "accounts"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _items(value)
            if nested:
                return nested
    return [payload]


def _parse_item(item: dict, *, fallback_username: str, provider: str) -> ManagedLiveStatus:
    username = _username_from_item(item) or fallback_username
    outcome = _outcome(item)
    room = item.get("room") if isinstance(item.get("room"), dict) else {}
    room_id = item.get("room_id") or item.get("roomId") or room.get("id")
    title = item.get("room_title") or item.get("title") or room.get("title")
    viewers = (
        item.get("viewer_count")
        or item.get("viewerCount")
        or item.get("user_count")
        or room.get("viewer_count")
    )
    if outcome is None:
        return ManagedLiveStatus(
            username=username,
            outcome="unknown",
            source=f"managed:{provider}",
            error="managed API response has no explicit live status",
        )
    return ManagedLiveStatus(
        username=username,
        outcome=outcome,
        room_id=str(room_id).strip() if room_id is not None else None,
        title=str(title).strip() if title else None,
        viewer_count=_as_int(viewers),
        source=f"managed:{provider}",
    )


def fetch_managed_statuses(usernames: list[str], config: dict) -> dict[str, ManagedLiveStatus]:
    """Fetch explicit statuses from a configured professional API.

    Batch endpoint contract:
      POST {"usernames": ["name"]} -> {"data": [{"username": "name", "is_live": true}]}
    An endpoint containing ``{username}`` is queried once per account with GET.
    """
    clean_names = [_clean_username(name) for name in usernames if _clean_username(name)]
    if not clean_names:
        return {}

    provider = str(config.get("provider") or "generic").strip().lower()
    endpoint = str(os.getenv("TIKTOK_LIVE_API_ENDPOINT") or config.get("endpoint") or "").strip()
    api_key = str(os.getenv("TIKTOK_LIVE_API_KEY") or config.get("api_key") or "").strip()
    timeout = max(3.0, min(180.0, float(config.get("timeout") or 30.0)))
    unavailable = {
        name.casefold(): ManagedLiveStatus(
            username=name,
            outcome="unknown",
            source=f"managed:{provider}",
            error="managed LIVE API endpoint or key is not configured",
        )
        for name in clean_names
    }
    if provider == "apify" and not endpoint:
        endpoint = (
            "https://api.apify.com/v2/acts/"
            "unseenuser~tiktok-live-status-scraper/run-sync-get-dataset-items"
        )
    if not endpoint or not api_key:
        return unavailable

    auth_header = str(config.get("auth_header") or "Authorization").strip()
    auth_scheme = str(config.get("auth_scheme") or "Bearer").strip()
    auth_value = f"{auth_scheme} {api_key}".strip()
    headers = {"Accept": "application/json", auth_header: auth_value}
    results = dict(unavailable)

    try:
        if provider == "apify":
            response = requests.post(
                endpoint,
                params={"token": api_key},
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                json={"handles": clean_names, "include_stream_urls": True},
                timeout=timeout,
            )
            response.raise_for_status()
            for item in _items(response.json()):
                status = _parse_item(item, fallback_username="", provider=provider)
                key = status.username.casefold()
                if key in results:
                    results[key] = status
            return results

        if "{username}" in endpoint:
            for name in clean_names:
                response = requests.get(
                    endpoint.format(username=name),
                    headers=headers,
                    timeout=timeout,
                )
                response.raise_for_status()
                parsed = _items(response.json())
                if parsed:
                    results[name.casefold()] = _parse_item(
                        parsed[0], fallback_username=name, provider=provider
                    )
            return results

        response = requests.post(
            endpoint,
            headers={**headers, "Content-Type": "application/json"},
            json={"usernames": clean_names},
            timeout=timeout,
        )
        response.raise_for_status()
        parsed = _items(response.json())
        for item in parsed:
            status = _parse_item(item, fallback_username="", provider=provider)
            key = status.username.casefold()
            if key in results:
                results[key] = status
        return results
    except (requests.RequestException, ValueError) as exc:
        message = f"managed LIVE API request failed: {exc}"
        for status in results.values():
            status.error = message
        return results
