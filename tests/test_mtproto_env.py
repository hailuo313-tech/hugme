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
    from core.config import Settings

    key = Fernet.generate_key().decode()
    
    # 创建一个有效的 Settings 对象
    test_settings = Settings()
    test_settings.TELEGRAM_API_ID = 12345
    test_settings.TELEGRAM_API_HASH = "abc123realhash"
    test_settings.TELEGRAM_SESSION_FERNET_KEY = key
    test_settings.TELEGRAM_SESSION_STRINGS = "1BVtsOHwBu5Xexample"
    test_settings.TELEGRAM_SESSION_DIR = "./data/telegram_sessions"
    
    # 临时替换 settings
    import app.core.mtproto_env as mtproto_module
    original_settings = mtproto_module.settings
    mtproto_module.settings = test_settings
    
    try:
        ok, issues = mtproto_env_status()
        assert ok is True
        assert issues == []
    finally:
        # 恢复原始 settings
        mtproto_module.settings = original_settings
