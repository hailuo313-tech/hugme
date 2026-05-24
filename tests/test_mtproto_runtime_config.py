from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_compose_enables_mtproto_session_restore_by_default() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "MTProto_ENABLED: ${MTProto_ENABLED:-1}" in compose
    assert "SESSION_MANAGER_ENABLED: ${SESSION_MANAGER_ENABLED:-1}" in compose


def test_api_startup_accepts_session_manager_enabled_flag() -> None:
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

    assert 'getattr(settings, "MTProto_ENABLED", False)' in main
    assert 'getattr(settings, "SESSION_MANAGER_ENABLED", False)' in main
    assert "await session_manager.start()" in main
