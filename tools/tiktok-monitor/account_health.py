"""Detect banned / unavailable TikTok accounts via profile page."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

import requests

from accounts_store import account_url

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

# TikTok webapp.user-detail.statusCode (observed)
STATUS_OK = 0
STATUS_NOT_FOUND = 10221
STATUS_BANNED = 10202

REASON_OK = "ok"
REASON_BANNED = "banned"
REASON_NOT_FOUND = "not_found"
REASON_UNAVAILABLE = "unavailable"
REASON_ERROR = "error"


@dataclass
class AccountHealth:
    username: str
    ok: bool
    reason: str = REASON_OK
    status_code: Optional[int] = None
    detail: Optional[str] = None
    profile_url: Optional[str] = None
    display_name: Optional[str] = None


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
        if ch == "{": depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    payload = json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
                return payload if isinstance(payload, dict) else None
    return None


def _user_detail(html: str) -> tuple[Optional[dict], Optional[int]]:
    blob = extract_json_blob(html, "__UNIVERSAL_DATA_FOR_REHYDRATION__")
    if not blob:
        return None, None
    scope = blob.get("__DEFAULT_SCOPE__")
    if not isinstance(scope, dict):
        return None, None

    detail = scope.get("webapp.user-detail")
    if not isinstance(detail, dict):
        webapp = scope.get("webapp")
        if isinstance(webapp, dict):
            detail = webapp.get("user-detail")

    if not isinstance(detail, dict):
        return None, None

    status_code = detail.get("statusCode")
    try:
        code = int(status_code) if status_code is not None else None
    except (TypeError, ValueError):
        code = None
    user_info = detail.get("userInfo")
    return user_info if isinstance(user_info, dict) else None, code


def _visible_banned(html: str) -> bool:
    """Strict ban-page check — avoid matching ban strings inside JS bundles."""
    if re.search(r"<title[^>]*>[^<]*account (?:has been )?banned", html, re.I):
        return True
    if re.search(
        r'class="[^"]*(?:error|ban)[^"]*"[^>]*>\s*[^<]{0,200}(?:account (?:has been )?banned|account was suspended)',
        html,
        re.I | re.S,
    ):
        return True
    return False


def _reason_from_status(
    status_code: Optional[int], html: str, has_user_info: bool
) -> tuple[bool, str, str]:
    if status_code == STATUS_OK:
        return True, REASON_OK, "账号正常"
    if status_code == STATUS_BANNED:
        return False, REASON_BANNED, f"账号被封禁 (statusCode={status_code})"
    if status_code == STATUS_NOT_FOUND:
        return False, REASON_NOT_FOUND, f"账号不存在或已注销 (statusCode={status_code})"
    if status_code is not None and status_code != STATUS_OK:
        return False, REASON_UNAVAILABLE, f"账号不可用 (statusCode={status_code})"
    if has_user_info:
        return True, REASON_OK, "账号正常"
    if _visible_banned(html):
        return False, REASON_BANNED, "页面提示账号被封禁"
    return False, REASON_ERROR, "无法解析账号状态"


def check_account_health(username: str, timeout: float = 20.0) -> AccountHealth:
    clean = username.lstrip("@").strip()
    profile_url = account_url(clean)
    if not clean:
        return AccountHealth(
            username=username,
            ok=False,
            reason=REASON_ERROR,
            detail="用户名为空",
            profile_url=profile_url,
        )

    try:
        resp = requests.get(
            profile_url,
            headers=DEFAULT_HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
        html = resp.text
    except requests.RequestException as exc:
        return AccountHealth(
            username=clean,
            ok=False,
            reason=REASON_ERROR,
            detail=str(exc),
            profile_url=profile_url,
        )

    user_info, status_code = _user_detail(html)
    display_name = None
    unique_id = None
    if user_info:
        user = user_info.get("user")
        if isinstance(user, dict):
            display_name = str(user.get("nickname") or user.get("uniqueId") or clean)
            unique_id = str(user.get("uniqueId") or clean)

    has_user_info = bool(user_info and unique_id)
    ok, reason, detail = _reason_from_status(status_code, html, has_user_info)

    return AccountHealth(
        username=clean,
        ok=ok,
        reason=reason,
        status_code=status_code,
        detail=detail,
        profile_url=profile_url,
        display_name=display_name or clean,
    )
