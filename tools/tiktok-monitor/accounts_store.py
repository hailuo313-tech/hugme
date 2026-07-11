"""TikTok account list stored in config.json (CRUD for live monitor MVP)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

GROUP_OWN = "own"
GROUP_INTERCEPT = "intercept"
VALID_GROUPS = {GROUP_OWN, GROUP_INTERCEPT}
GROUP_LABELS = {
    GROUP_OWN: "自有账号",
    GROUP_INTERCEPT: "截流账号",
}


@dataclass
class Account:
    name: str
    username: str
    url: str
    group: str = GROUP_OWN


def normalize_group(value: str | None, *, default: str = GROUP_OWN) -> str:
    raw = str(value or "").strip().lower()
    if raw in VALID_GROUPS:
        return raw
    if raw in {"自有", "自有账号"}:
        return GROUP_OWN
    if raw in {"截流", "截流账号"}:
        return GROUP_INTERCEPT
    return default if default in VALID_GROUPS else GROUP_OWN


def normalize_username(username: str | None, url: str | None = None) -> str | None:
    value = str(username or "").strip()
    if value.startswith("@"):
        value = value[1:]
    if value:
        return value
    parsed = urlparse(str(url or ""))
    match = re.search(r"/@([^/?#]+)", parsed.path)
    if match:
        return match.group(1)
    return None


def account_url(username: str) -> str:
    return f"https://www.tiktok.com/@{username.lstrip('@')}"


def parse_account_input(value: str, *, name: str = "", group: str = GROUP_OWN) -> Account:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("账号不能为空")
    username = normalize_username(raw, raw)
    url = raw if raw.startswith("http") else account_url(username or raw.lstrip("@"))
    username = normalize_username(username, url)
    if not username:
        raise ValueError("无法解析 TikTok 账号")
    display = (name or username or raw).strip()
    return Account(
        name=display,
        username=username,
        url=url,
        group=normalize_group(group),
    )


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "accounts": [],
            "live_monitor": {
                "auto_probe_enabled": False,
                "auto_sample_enabled": False,
            },
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config.json 必须是 JSON 对象")
    data.setdefault("accounts", [])
    data.setdefault(
        "live_monitor",
        {"auto_probe_enabled": False, "auto_sample_enabled": False},
    )
    return data


def save_config(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def list_accounts(path: Path, *, group: Optional[str] = None) -> list[Account]:
    data = load_config(path)
    rows: list[Account] = []
    want = normalize_group(group) if group else None
    for idx, item in enumerate(data.get("accounts") or [], start=1):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        username = normalize_username(str(item.get("username") or "").strip() or None, url)
        if not url and username:
            url = account_url(username)
        if not username:
            continue
        acc_group = normalize_group(str(item.get("group") or ""))
        if want and acc_group != want:
            continue
        rows.append(
            Account(
                name=str(item.get("name") or username or f"account-{idx}").strip(),
                username=username,
                url=url,
                group=acc_group,
            )
        )
    return rows


def account_group_map(path: Path) -> dict[str, str]:
    return {acc.username.casefold(): acc.group for acc in list_accounts(path)}


def add_account(path: Path, account: Account) -> bool:
    data = load_config(path)
    current = data.setdefault("accounts", [])
    if not isinstance(current, list):
        current = []
        data["accounts"] = current
    seen = {
        (normalize_username(str(x.get("username") or ""), str(x.get("url") or "")) or "").casefold()
        for x in current
        if isinstance(x, dict)
    }
    key = account.username.casefold()
    if not key or key in seen:
        return False
    current.append(
        {
            "name": account.name,
            "username": account.username,
            "url": account.url,
            "group": normalize_group(account.group),
        }
    )
    save_config(path, data)
    return True


def add_accounts_from_text(path: Path, text: str, *, group: str = GROUP_OWN) -> int:
    added = 0
    acc_group = normalize_group(group)
    for line in text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        account = parse_account_input(raw, group=acc_group)
        if add_account(path, account):
            added += 1
    return added


def delete_account(path: Path, username: str) -> bool:
    clean = username.lstrip("@").strip()
    if not clean:
        return False
    data = load_config(path)
    accounts = data.get("accounts")
    if not isinstance(accounts, list):
        return False
    kept: list[Any] = []
    removed = False
    for item in accounts:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        item_username = str(item.get("username") or "").lstrip("@").strip()
        item_url = str(item.get("url") or "")
        if item_username.lower() == clean.lower() or f"/@{clean.lower()}" in item_url.lower():
            removed = True
            continue
        kept.append(item)
    if not removed:
        return False
    data["accounts"] = kept
    save_config(path, data)
    return True
