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


def test_api_startup_wires_proactive_workers() -> None:
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

    assert 'start_silent_reactivation_scheduler' in main
    assert 'start_notification_sender_worker' in main
    assert 'start_message_schedule_scheduler' in main
    assert 'start_auto_delivery_worker' in main
    assert 'shutdown_silent_reactivation_scheduler' in main
    assert 'shutdown_notification_sender_worker' in main
    assert 'shutdown_message_schedule_scheduler' in main
    assert 'shutdown_auto_delivery_worker' in main
