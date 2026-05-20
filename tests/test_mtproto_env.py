"""C-03: MTProto env template and validation helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import Settings
from core.mtproto_env import mtproto_env_status


def test_env_template_lists_required_mtproto_keys():
    root = Path(__file__).resolve().parents[1]
    text = (root / ".env.template").read_text(encoding="utf-8")
    for key in (
        "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH",
        "TELEGRAM_SESSION_FERNET_KEY",
        "TELEGRAM_SESSION_STRINGS",
        "TELEGRAM_SESSION_DIR",
    ):
        assert f"{key}=" in text


def test_mtproto_env_status_incomplete_by_default(monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_ID", "")
    monkeypatch.setenv("TELEGRAM_API_HASH", "")
    monkeypatch.setenv("TELEGRAM_SESSION_FERNET_KEY", "")
    monkeypatch.setenv("TELEGRAM_SESSION_STRINGS", "")
    # Reload settings from patched env
    from core import config

    monkeypatch.setattr(config, "settings", Settings())
    ok, issues = mtproto_env_status()
    assert ok is False
    assert issues


def test_mtproto_env_status_ok_with_valid_fernet(monkeypatch):
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "abc123realhash")
    monkeypatch.setenv("TELEGRAM_SESSION_FERNET_KEY", key)
    monkeypatch.setenv("TELEGRAM_SESSION_STRINGS", "1BVtsOHwBu5Xexample")
    
    # 重新导入 config 以获取新的环境变量
    import importlib
    from core import config
    importlib.reload(config)
    
    ok, issues = mtproto_env_status()
    assert ok is True
    assert issues == []
