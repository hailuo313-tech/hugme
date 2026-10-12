"""Insert Step B real-runtime hooks. Does not rebuild the main API."""

from __future__ import annotations

from pathlib import Path

ROOT = Path("/opt/eris")


def _load(rel: str) -> tuple[Path, str, str]:
    path = ROOT / rel
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8").replace("\r\n", "\n")
    return path, text, newline


def must_replace(rel: str, old: str, new: str, label: str) -> None:
    path, text, newline = _load(rel)
    old = old.replace("\r\n", "\n")
    new = new.replace("\r\n", "\n")
    if new.strip() in text and old not in text:
        print("skip", label, "(already present)")
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match in {rel}, found {count}")
    path.write_text(text.replace(old, new, 1).replace("\n", newline), encoding="utf-8")
    print("patched", label)


def main() -> None:
    must_replace(
        "app/core/process_role.py",
        """def is_shadow_runtime(role: str | None = None) -> bool:
    resolved = normalize_process_role(role if role is not None else _active_role)
    return resolved == ROLE_TELEGRAM_RUNTIME and _shadow_mode_enabled()
""",
        """def is_shadow_runtime(role: str | None = None) -> bool:
    resolved = normalize_process_role(role if role is not None else _active_role)
    return resolved == ROLE_TELEGRAM_RUNTIME and _shadow_mode_enabled()


def is_dedicated_telegram_runtime(role: str | None = None) -> bool:
    resolved = normalize_process_role(role if role is not None else _active_role)
    return resolved == ROLE_TELEGRAM_RUNTIME and not is_shadow_runtime(resolved)
""",
        "dedicated runtime helper",
    )
    must_replace(
        "app/core/process_role.py",
        """    if is_shadow_runtime(resolved):
        steps.append("start:shadow_consumer")
        steps.append("mark:runtime_ready")
        return tuple(steps)
    if owns_api_workers(resolved):
""",
        """    if is_shadow_runtime(resolved):
        steps.append("start:shadow_consumer")
        steps.append("mark:runtime_ready")
        return tuple(steps)
    if resolved == ROLE_TELEGRAM_RUNTIME:
        steps.append("start:runtime_consumer")
        steps.append("mark:runtime_ready")
        return tuple(steps)
    if owns_api_workers(resolved):
""",
        "startup sequence",
    )
    must_replace(
        "app/core/process_role.py",
        """    resolved = normalize_process_role(role if role is not None else _active_role)
    steps: list[str] = []
    if owns_telegram_runtime(resolved):
""",
        """    resolved = normalize_process_role(role if role is not None else _active_role)
    steps: list[str] = []
    if is_shadow_runtime(resolved):
        steps.append("stop:shadow_consumer")
        return tuple(steps)
    if resolved == ROLE_TELEGRAM_RUNTIME:
        steps.append("stop:runtime_consumer")
        return tuple(steps)
    if owns_telegram_runtime(resolved):
""",
        "shutdown sequence",
    )
    must_replace(
        "app/main.py",
        """    is_shadow_runtime,
""",
        """    is_dedicated_telegram_runtime,
    is_shadow_runtime,
""",
        "main import dedicated helper",
    )
    must_replace(
        "app/main.py",
        """from services.runtime_shadow_consumer import start_shadow_consumer, stop_shadow_consumer
""",
        """from services.runtime_command_consumer import start_runtime_consumer, stop_runtime_consumer
from services.runtime_shadow_consumer import start_shadow_consumer, stop_shadow_consumer
""",
        "main import real consumer",
    )
    must_replace(
        "app/main.py",
        """            logger.bind(error_type=type(exc).__name__).warning(
                "runtime_shadow.consumer.start_failed"
            )
    elif owns_telegram_runtime(role):
""",
        """            logger.bind(error_type=type(exc).__name__).warning(
                "runtime_shadow.consumer.start_failed"
            )
    elif is_dedicated_telegram_runtime(role):
        telegram_ready = True
        if _mtproto_runtime_enabled():
            try:
                await session_manager.start()
                logger.info("mtproto.session_manager.started")
            except Exception as exc:
                telegram_ready = False
                logger.bind(error_type=type(exc).__name__).error(
                    "mtproto.session_manager.start_failed"
                )
        try:
            await start_runtime_consumer()
        except Exception as exc:
            telegram_ready = False
            logger.bind(error_type=type(exc).__name__).error(
                "runtime_consumer.start_failed"
            )
        mark_runtime_ready(telegram_ready)
    elif owns_telegram_runtime(role):
""",
        "main dedicated startup",
    )
    must_replace(
        "app/main.py",
        """            "runtime_shadow.consumer.stop_failed"
        )

    if is_shadow_runtime(role):
""",
        """            "runtime_shadow.consumer.stop_failed"
        )
    try:
        await stop_runtime_consumer()
    except Exception as exc:
        logger.bind(error_type=type(exc).__name__).warning(
            "runtime_consumer.stop_failed"
        )

    if is_shadow_runtime(role):
""",
        "main stop consumer",
    )
    must_replace(
        "app/main.py",
        """        logger.bind(component="runtime", process_role=role).info("process_role.shutdown.complete")
        return

    if owns_telegram_runtime(role):
""",
        """        logger.bind(component="runtime", process_role=role).info("process_role.shutdown.complete")
        return

    if is_dedicated_telegram_runtime(role):
        if _mtproto_runtime_enabled():
            try:
                await session_manager.stop()
                logger.info("mtproto.session_manager.stopped")
            except Exception as exc:
                logger.bind(error_type=type(exc).__name__).warning(
                    "mtproto.session_manager.stop_failed"
                )
        mark_runtime_ready(False)
        logger.bind(component="runtime", process_role=role).info("process_role.shutdown.complete")
        return

    if owns_telegram_runtime(role):
""",
        "main dedicated shutdown",
    )
    must_replace(
        "app/services/runtime_shadow_consumer.py",
        """    WHERE status = 'pending'
      AND available_at <= NOW()
""",
        """    WHERE status = 'pending'
      AND available_at <= NOW()
      AND command_type NOT IN (
          'connect_account', 'disconnect_account', 'delete_account', 'sync_account', 'reconnect_account',
          'send_message', 'send_media', 'send_text', 'outbound_message', 'call_start', 'call_outbound',
          'answer_call', 'reject_call', 'hangup_call'
      )
""",
        "shadow claim excludes send/connect",
    )
    print("step B patches applied")


if __name__ == "__main__":
    main()
