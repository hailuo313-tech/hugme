"""Fetch TikTok live room status and viewer counts."""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class LiveStatus:
    username: str
    is_live: bool
    room_id: Optional[str] = None
    title: Optional[str] = None
    viewer_count: Optional[int] = None
    enter_count: Optional[int] = None
    source: str = "web"
    error: Optional[str] = None

    @property
    def outcome(self) -> str:
        if self.error:
            return "unknown"
        return "live" if self.is_live else "offline"


def _get_with_retry(
    url: str,
    *,
    timeout: float,
    retries: int = 1,
    **kwargs: Any,
) -> requests.Response:
    """GET with a short retry for transient network, rate-limit and 5xx errors."""
    last_error: Optional[Exception] = None
    for attempt in range(max(0, retries) + 1):
        try:
            response = requests.get(url, timeout=timeout, **kwargs)
            if response.status_code == 429 or response.status_code >= 500:
                response.raise_for_status()
            if response.status_code >= 400:
                response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= max(0, retries):
                break
            time.sleep((0.35 * (2**attempt)) + random.uniform(0.05, 0.25))
    assert last_error is not None
    raise last_error


def extract_json_blob(text: str, marker: str) -> Optional[dict]:
    idx = text.find(marker)
    if idx < 0:
        return None
    start = text.find("{", idx)
    if start < 0:
        return None
    depth = 0
    for i in range(start, min(len(text), start + 3_000_000)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    payload = json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
                return payload if isinstance(payload, dict) else None
    return None


def _dig(obj: Any, *keys: str) -> Any:
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _as_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _offline_page_strict(html: str) -> bool:
    """Only treat as offline when the visible page says so, not i18n bundles."""
    if re.search(r"<title[^>]*>[^<]*live has ended", html, re.I):
        return True
    if re.search(
        r'id="[^"]*live-ended[^"]*"[^>]*>|class="[^"]*live-end[^"]*"[^>]*>',
        html,
        re.I,
    ):
        return True
    return False


def _sigi_live_room(html: str) -> Optional[dict]:
    sigi = extract_json_blob(html, "SIGI_STATE")
    if not sigi:
        return None
    info = _dig(sigi, "LiveRoom", "liveRoomUserInfo")
    return info if isinstance(info, dict) else None


def _room_id_from_regex(html: str) -> Optional[str]:
    for pattern in (
        r'"roomId"\s*:\s*"(\d+)"',
        r'"room_id"\s*:\s*"(\d+)"',
        r'"roomId"\s*:\s*(\d+)',
    ):
        match = re.search(pattern, html)
        if match:
            text = str(match.group(1)).strip()
            if text:
                return text
    return None


def _room_id_from_live_html(html: str) -> Optional[str]:
    info = _sigi_live_room(html)
    if info:
        user = info.get("user") if isinstance(info.get("user"), dict) else {}
        room = info.get("liveRoom") if isinstance(info.get("liveRoom"), dict) else {}
        room_id = user.get("roomId") or room.get("roomId")
        if room_id is not None:
            text = str(room_id).strip()
            if text:
                return text
    return _room_id_from_regex(html)


def _live_from_sigi(info: dict) -> tuple[Optional[str], bool, Optional[str], Optional[int], Optional[int]]:
    user = info.get("user") if isinstance(info.get("user"), dict) else {}
    room = info.get("liveRoom") if isinstance(info.get("liveRoom"), dict) else {}
    room_id = str(user.get("roomId") or room.get("roomId") or "").strip() or None
    status = _as_int(room.get("status"))
    if status is None:
        status = _as_int(user.get("status"))

    stats = room.get("liveRoomStats") if isinstance(room.get("liveRoomStats"), dict) else {}
    viewers = _as_int(stats.get("userCount"))
    enter_count = _as_int(stats.get("enterCount"))
    title = str(room.get("title") or "").strip() or None
    stream_data = room.get("streamData")
    has_stream = isinstance(stream_data, dict) and bool(stream_data)

    is_live = bool(room_id) and status == 4 and has_stream
    return room_id, is_live, title, viewers, enter_count


def _stream_urls_from_sigi(info: dict) -> list[str]:
    room = info.get("liveRoom") if isinstance(info.get("liveRoom"), dict) else {}
    stream_data = room.get("streamData")
    urls: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for child in value.values():
                collect(child)
            return
        if isinstance(value, list):
            for child in value:
                collect(child)
            return
        if not isinstance(value, str):
            return
        candidate = value.replace("\\u0026", "&").replace("\\/", "/").strip()
        if candidate.startswith(("{", "[")):
            try:
                collect(json.loads(candidate))
                return
            except json.JSONDecodeError:
                pass
        if candidate.startswith(("https://", "http://")) and (
            ".flv" in candidate or ".m3u8" in candidate or "pull" in candidate
        ):
            if candidate not in urls:
                urls.append(candidate)

    collect(stream_data)
    return urls


def validate_playback_stream(info: dict, timeout: float = 6.0) -> bool:
    """Confirm that a SIGI playback URL currently returns playable bytes."""
    headers = {
        **DEFAULT_HEADERS,
        "Accept": "*/*",
        "Referer": "https://www.tiktok.com/",
        "Range": "bytes=0-4095",
    }
    for url in _stream_urls_from_sigi(info)[:3]:
        response: Optional[requests.Response] = None
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=(min(timeout, 4.0), timeout),
                stream=True,
                allow_redirects=True,
            )
            if response.status_code not in (200, 206):
                continue
            chunk = next(response.iter_content(chunk_size=4096), b"")
            content_type = str(response.headers.get("content-type") or "").lower()
            if not chunk:
                continue
            if b"#EXTM3U" in chunk[:128]:
                return True
            if "video/" in content_type or "octet-stream" in content_type:
                return True
            if chunk[:3] == b"FLV":
                return True
        except (requests.RequestException, StopIteration):
            continue
        finally:
            if response is not None:
                response.close()
    return False


def _sigi_explicitly_offline(info: dict) -> bool:
    user = info.get("user") if isinstance(info.get("user"), dict) else {}
    room = info.get("liveRoom") if isinstance(info.get("liveRoom"), dict) else {}
    status = _as_int(room.get("status"))
    if status is None:
        status = _as_int(user.get("status"))
    return status is not None and status != 4


def _redirected_away_from_live(response: requests.Response, username: str) -> bool:
    path = urlparse(str(response.url or "")).path.rstrip("/").lower()
    expected = f"/@{username.lower()}/live"
    return bool(path) and path != expected and "/live" not in path


def fetch_webcast_room(
    room_id: str,
    timeout: float = 20.0,
    retries: int = 1,
) -> Optional[dict]:
    if not room_id:
        return None
    try:
        resp = _get_with_retry(
            "https://webcast.tiktok.com/webcast/room/info/",
            params={"aid": "1988", "room_id": room_id},
            headers=DEFAULT_HEADERS,
            timeout=timeout,
            retries=retries,
        )
        payload = resp.json()
    except (requests.RequestException, ValueError):
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else None


def is_webcast_live(data: Optional[dict]) -> bool:
    if not data:
        return False
    finish_time = _as_int(data.get("finish_time")) or 0
    finish_reason = _as_int(data.get("finish_reason"))
    if finish_time > 0 or finish_reason not in (None, 0):
        return False

    stream_status = _as_int(data.get("stream_status"))
    if stream_status is not None:
        return stream_status == 1

    status = _as_int(data.get("status"))
    if status != 4:
        return False

    user_count = _as_int(data.get("user_count")) or 0
    return bool(data.get("stream_id")) and user_count > 0


def viewer_count_from_webcast(data: Optional[dict]) -> Optional[int]:
    if not data:
        return None
    for key in ("user_count", "viewerCount", "total_user"):
        value = _as_int(data.get(key))
        if value is not None:
            return value
    stats = data.get("liveRoomStats")
    if isinstance(stats, dict):
        return _as_int(stats.get("userCount"))
    return None


def _pick_viewer_count(primary: Optional[int], fallback: Optional[int]) -> Optional[int]:
    if primary is not None and primary > 0:
        return primary
    if fallback is not None:
        return fallback
    if primary is not None:
        return primary
    return None


def title_from_webcast(data: Optional[dict]) -> Optional[str]:
    if not data:
        return None
    title = data.get("title")
    if title is None:
        return None
    text = str(title).strip()
    return text or None


def fetch_live_metrics(
    *,
    username: Optional[str] = None,
    room_id: Optional[str] = None,
    timeout: float = 20.0,
) -> tuple[Optional[int], Optional[int]]:
    """Return (userCount reference, enterCount) from the live page SIGI payload."""
    clean = str(username or "").lstrip("@").strip()
    if not clean and not room_id:
        return None, None
    live_url = f"https://www.tiktok.com/@{clean}/live" if clean else None
    try:
        resp = _get_with_retry(
            live_url or f"https://www.tiktok.com/",
            headers=DEFAULT_HEADERS,
            timeout=timeout,
            retries=1,
            allow_redirects=True,
        )
        html = resp.text
    except requests.RequestException:
        return None, None
    info = _sigi_live_room(html)
    if not info:
        return None, None
    _, is_live, _, viewers, enter_count = _live_from_sigi(info)
    if not is_live:
        return None, None
    return viewers, enter_count


def fetch_live_status(
    username: str,
    timeout: float = 20.0,
    retries: int = 1,
) -> LiveStatus:
    clean = username.lstrip("@").strip()
    if not clean:
        return LiveStatus(username=username, is_live=False, error="empty username")

    live_url = f"https://www.tiktok.com/@{clean}/live"
    try:
        resp = _get_with_retry(
            live_url,
            headers=DEFAULT_HEADERS,
            timeout=timeout,
            retries=retries,
            allow_redirects=True,
        )
        html = resp.text
    except requests.RequestException as exc:
        return LiveStatus(username=clean, is_live=False, error=str(exc))

    sigi_info = _sigi_live_room(html)
    if sigi_info:
        room_id, is_live, title, viewers, enter_count = _live_from_sigi(sigi_info)
        stream_urls = _stream_urls_from_sigi(sigi_info)

        # Strongest server-reachable proof of a live stream: the playback URL
        # actually returns playable bytes. This holds even when TikTok's status
        # flag is not 4 and when the Webcast API is blocked for datacenter IPs,
        # which is exactly the false-negative case we observed in production.
        if stream_urls and validate_playback_stream(sigi_info, timeout=min(timeout, 8.0)):
            return LiveStatus(
                username=clean,
                is_live=True,
                room_id=room_id,
                title=title,
                viewer_count=viewers,
                enter_count=enter_count,
                source="sigi+stream",
            )

        if room_id:
            webcast = fetch_webcast_room(room_id, timeout=timeout, retries=retries)
            if is_webcast_live(webcast):
                wc_viewers = viewer_count_from_webcast(webcast)
                return LiveStatus(
                    username=clean,
                    is_live=True,
                    room_id=room_id,
                    title=title or title_from_webcast(webcast),
                    viewer_count=_pick_viewer_count(wc_viewers, viewers),
                    enter_count=enter_count,
                    source="sigi+webcast",
                )

        if is_live or stream_urls:
            return LiveStatus(
                username=clean,
                is_live=False,
                room_id=room_id,
                title=title,
                viewer_count=viewers,
                enter_count=enter_count,
                source="sigi_unverified",
                error="SIGI live candidate failed Webcast and playback verification",
            )

    room_id = _room_id_from_live_html(html)
    if room_id:
        webcast = fetch_webcast_room(room_id, timeout=timeout, retries=retries)
        if is_webcast_live(webcast):
            sigi_viewers = None
            sigi_enter = None
            title = None
            if sigi_info:
                _, _, title, sigi_viewers, sigi_enter = _live_from_sigi(sigi_info)
            wc_viewers = viewer_count_from_webcast(webcast)
            return LiveStatus(
                username=clean,
                is_live=True,
                room_id=room_id,
                title=title_from_webcast(webcast) or title,
                viewer_count=_pick_viewer_count(wc_viewers, sigi_viewers),
                enter_count=sigi_enter,
                source="webcast",
            )

    if _offline_page_strict(html):
        return LiveStatus(username=clean, is_live=False, source="live_page")

    if sigi_info and _sigi_explicitly_offline(sigi_info):
        return LiveStatus(username=clean, is_live=False, room_id=room_id, source="sigi")

    if _redirected_away_from_live(resp, clean):
        return LiveStatus(username=clean, is_live=False, room_id=room_id, source="redirect")

    return LiveStatus(
        username=clean,
        is_live=False,
        room_id=room_id,
        source="live_page",
        error="TikTok response did not contain a conclusive live/offline signal",
    )


def fetch_viewer_count(
    room_id: str,
    *,
    username: Optional[str] = None,
    timeout: float = 20.0,
) -> Optional[int]:
    viewers, _ = fetch_live_metrics(username=username, room_id=room_id, timeout=timeout)
    if viewers is not None:
        return viewers
    data = fetch_webcast_room(room_id, timeout=timeout)
    if not is_webcast_live(data):
        return None
    count = viewer_count_from_webcast(data)
    return count if count is not None else 0


def fetch_enter_count(
    *,
    username: str,
    timeout: float = 20.0,
) -> Optional[int]:
    _, enter_count = fetch_live_metrics(username=username, timeout=timeout)
    return enter_count
