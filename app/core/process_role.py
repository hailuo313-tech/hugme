"""Process role helpers for API / Telegram Runtime split.

Stage 1 keeps production on ``all``. ``api`` and ``telegram_runtime`` are
compatible roles so later stages can split processes without double-starting
schedulers or Telegram sessions.
"""

from __future__ import annotations

from typing import Iterable

ROLE_ALL = "all"
ROLE_API = "api"
ROLE_TELEGRAM_RUNTIME = "telegram_runtime"
VALID_ROLES = frozenset({ROLE_ALL, ROLE_API, ROLE_TELEGRAM_RUNTIME})

API_WORKER_NAMES = (
    "embedding_worker",
    "profile_score_scheduler",
    "archive_worker",
    "human_takeover_release_worker",
)

TELEGRAM_WORKER_NAMES = (
    "silent_reactivation_scheduler",
    "notification_sender_worker",
    "message_schedule_scheduler",
    "auto_delivery_worker",
    "fixed_auto_reply_worker",
    "telegram_user_migration_worker",
    "video_reinvite_worker",
    "call_broadcast_worker",
)

_active_role = ROLE_ALL
_runtime_ready = False


def _shadow_mode_enabled() -> bool:
    try:
        from core.config import settings

        return bool(getattr(settings, "RUNTIME_SHADOW_MODE", False))
    except Exception:
        return False


def is_shadow_runtime(role: str | None = None) -> bool:
    resolved = normalize_process_role(role if role is not None else _active_role)
    return resolved == ROLE_TELEGRAM_RUNTIME and _shadow_mode_enabled()


def is_dedicated_telegram_runtime(role: str | None = None) -> bool:
    resolved = normalize_process_role(role if role is not None else _active_role)
    return resolved == ROLE_TELEGRAM_RUNTIME and not is_shadow_runtime(resolved)


def normalize_process_role(value: object) -> str:
    raw = str(value or ROLE_ALL).strip().lower()
    if raw not in VALID_ROLES:
        return ROLE_ALL
    return raw


def owns_api_workers(role: str | None = None) -> bool:
    return normalize_process_role(role if role is not None else _active_role) in {
        ROLE_ALL,
        ROLE_API,
    }


def owns_telegram_runtime(role: str | None = None) -> bool:
    return normalize_process_role(role if role is not None else _active_role) in {
        ROLE_ALL,
        ROLE_TELEGRAM_RUNTIME,
    }


def owned_worker_names(role: str | None = None) -> tuple[str, ...]:
    resolved = normalize_process_role(role if role is not None else _active_role)
    names: list[str] = []
    if owns_api_workers(resolved):
        names.extend(API_WORKER_NAMES)
    if owns_telegram_runtime(resolved):
        names.extend(TELEGRAM_WORKER_NAMES)
    return tuple(names)


def scheduler_overlap(left_role: str, right_role: str) -> tuple[str, ...]:
    left = set(owned_worker_names(left_role))
    right = set(owned_worker_names(right_role))
    return tuple(sorted(left & right))


def set_active_process_role(role: object) -> str:
    global _active_role
    _active_role = normalize_process_role(role)
    return _active_role


def mark_runtime_ready(ready: bool = True) -> None:
    global _runtime_ready
    _runtime_ready = bool(ready)


def reset_runtime_state(role: str = ROLE_ALL) -> None:
    set_active_process_role(role)
    mark_runtime_ready(False)


def get_runtime_status() -> dict:
    role = normalize_process_role(_active_role)
    return {
        "process_role": role,
        "runtime_ready": bool(_runtime_ready),
        "owns_api_workers": owns_api_workers(role),
        "owns_telegram_runtime": owns_telegram_runtime(role),
    }


def warn_if_multi_worker(api_workers: object, role: str | None = None) -> bool:
    """Return True when Telegram runtime would be unsafe with uvicorn workers>1."""
    resolved = normalize_process_role(role if role is not None else _active_role)
    raw = str(api_workers or "1").strip() or "1"
    return owns_telegram_runtime(resolved) and raw != "1"


def startup_sequence(role: str | None = None) -> tuple[str, ...]:
    """Runtime Ready order used by the FastAPI startup handler."""
    resolved = normalize_process_role(role if role is not None else _active_role)
    steps: list[str] = []
    if is_shadow_runtime(resolved):
        steps.append("start:shadow_consumer")
        steps.append("mark:runtime_ready")
        return tuple(steps)
    if resolved == ROLE_TELEGRAM_RUNTIME:
        steps.append("start:session_manager")
        steps.append("start:runtime_consumer")
        steps.append("mark:runtime_ready")
        steps.append("start:message_schedule_scheduler")
        steps.append("start:auto_delivery_worker")
        steps.append("start:fixed_auto_reply_worker")
        steps.append("start:video_reinvite_worker")
        steps.append("start:incoming_call_listeners")
        return tuple(steps)
    if owns_api_workers(resolved):
        steps.extend(f"start:{name}" for name in API_WORKER_NAMES)
    if owns_telegram_runtime(resolved):
        steps.append("start:session_manager")
        steps.append("mark:runtime_ready")
        steps.extend(f"start:{name}" for name in TELEGRAM_WORKER_NAMES)
        steps.append("start:incoming_call_listeners")
    else:
        steps.append("mark:runtime_ready")
    return tuple(steps)


def shutdown_sequence(role: str | None = None) -> tuple[str, ...]:
    resolved = normalize_process_role(role if role is not None else _active_role)
    steps: list[str] = []
    if is_shadow_runtime(resolved):
        steps.append("stop:shadow_consumer")
        return tuple(steps)
    if resolved == ROLE_TELEGRAM_RUNTIME:
        steps.append("stop:incoming_call_listeners")
        steps.append("stop:video_reinvite_worker")
        steps.append("stop:fixed_auto_reply_worker")
        steps.append("stop:auto_delivery_worker")
        steps.append("stop:message_schedule_scheduler")
        steps.append("stop:runtime_consumer")
        steps.append("stop:session_manager")
        return tuple(steps)
    if owns_telegram_runtime(resolved):
        steps.append("stop:incoming_call_listeners")
        steps.extend(f"stop:{name}" for name in reversed(TELEGRAM_WORKER_NAMES))
        steps.append("stop:session_manager")
    if owns_api_workers(resolved):
        steps.extend(
            f"stop:{name}"
            for name in reversed(API_WORKER_NAMES)
            if name != "human_takeover_release_worker"
        )
    return tuple(steps)


def assert_exclusive_split(roles: Iterable[str] = (ROLE_API, ROLE_TELEGRAM_RUNTIME)) -> None:
    overlap = scheduler_overlap(*tuple(roles)[:2])
    if overlap:
        raise RuntimeError(f"process roles share schedulers: {overlap}")
