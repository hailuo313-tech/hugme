import asyncio
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from prometheus_fastapi_instrumentator import Instrumentator
import sys
import time
import uuid

from api.users import router as users_router
from api.messages import router as messages_router
from api.conversations import router as conversations_router
from api.memories import router as memories_router
from api.characters import router as characters_router
from api.handoff import router as handoff_router
from api.notifications import router as notifications_router
from api.payments import router as payments_router
from api.scripts import router as scripts_router
from api.health import router as health_router
from api.telegram import router as telegram_router
from api.telegram_accounts import router as telegram_accounts_router
from api.realtime import router as realtime_router
from api.llm import router as llm_router
from api.onboarding import router as onboarding_router
from api.admin import router as admin_router
from api.operator_quality import router as operator_quality_router
from api.ops_ai import router as ops_ai_router
from api.ai_ops_admin import router as ai_ops_admin_router
from api.ab_experiments import router as ab_experiments_router
from api.open_api import router as open_api_router
from api.geoip import router as geoip_router
from api.mtproto_sessions import router as mtproto_sessions_router
from api.monitoring import router as monitoring_router
from api.user_level import router as user_level_router
from api.message_schedule import router as message_schedule_router
from api.suspension import router as suspension_router
from api.auto_delivery import router as auto_delivery_router
from api.archive import router as archive_router
from api.intents import router as intents_router
from api.device_tokens import router as device_tokens_router
from api.metrics import router as metrics_router
from api.feature_flags import router as feature_flags_router
from api.attribution import router as attribution_router
from api.call_broadcast_admin import router as call_broadcast_admin_router
from api.fixed_auto_replies_admin import router as fixed_auto_replies_admin_router
from api.telegram_user_migration_admin import router as telegram_user_migration_admin_router
from api.video_reinvite_admin import router as video_reinvite_admin_router
from core.database import init_db
from core.config import settings
from core.process_role import (
    get_runtime_status,
    is_dedicated_telegram_runtime,
    is_shadow_runtime,
    mark_runtime_ready,
    normalize_process_role,
    owns_api_workers,
    owns_telegram_runtime,
    reset_runtime_state,
    set_active_process_role,
    warn_if_multi_worker,
)
from services.call_broadcast.incoming_review import restore_pending_reviews_from_db
from services.mtproto.session_manager import session_manager
from services.runtime_command_consumer import start_runtime_consumer, stop_runtime_consumer
from services.runtime_shadow_consumer import start_shadow_consumer, stop_shadow_consumer
from services.runtime_shadow_state import start_shadow_heartbeat, stop_shadow_heartbeat
from services.account_monitor import account_monitor
from services.alert_scheduler import alert_scheduler
from services.silent_reactivation_scheduler import (
    start_scheduler as start_silent_reactivation_scheduler,
    shutdown_scheduler as shutdown_silent_reactivation_scheduler,
)
from services.embedding_worker import (
    start_scheduler as start_embedding_worker,
    shutdown_scheduler as shutdown_embedding_worker,
)
from services.profile_score_scheduler import (
    start_scheduler as start_profile_score_scheduler,
    shutdown_scheduler as shutdown_profile_score_scheduler,
)
from services.notification_sender_worker import (
    start_scheduler as start_notification_sender_worker,
    shutdown_scheduler as shutdown_notification_sender_worker,
)
from services.message_schedule_service import (
    start_scheduler as start_message_schedule_scheduler,
    shutdown_scheduler as shutdown_message_schedule_scheduler,
)
from services.auto_delivery_worker import (
    start_scheduler as start_auto_delivery_worker,
    shutdown_scheduler as shutdown_auto_delivery_worker,
)
from services.archive_service import (
    start_scheduler as start_archive_worker,
    shutdown_scheduler as shutdown_archive_worker,
)
from services.human_takeover_release_worker import (
    start_scheduler as start_human_takeover_release_worker,
)
from services.call_broadcast.worker import (
    start_scheduler as start_call_broadcast_worker,
    shutdown_scheduler as shutdown_call_broadcast_worker,
)
from services.call_broadcast.incoming_listener import (
    start_incoming_call_listeners,
    shutdown_incoming_call_listeners,
)
from services.fixed_auto_reply_service import (
    start_scheduler as start_fixed_auto_reply_worker,
    shutdown_scheduler as shutdown_fixed_auto_reply_worker,
)
from services.telegram_user_migration import (
    start_scheduler as start_telegram_user_migration_worker,
    shutdown_scheduler as shutdown_telegram_user_migration_worker,
)
from services.video_reinvite import (
    start_scheduler as start_video_reinvite_worker,
    shutdown_scheduler as shutdown_video_reinvite_worker,
)
from services.telegram_account_health import run_health_check as run_telegram_account_health_check
from services.account_recovery_worker import (
    start_scheduler as start_account_recovery_worker,
    shutdown_scheduler as shutdown_account_recovery_worker,
)


def configure_logging():
    logger.remove()
    logger.add(
        sys.stdout,
        level="INFO",
        serialize=True,
        backtrace=False,
        diagnose=False,
    )


configure_logging()


def _start_scheduler(name: str, start_func) -> None:
    try:
        start_func()
    except Exception as exc:
        logger.bind(
            scheduler=name,
            error_type=type(exc).__name__,
        ).error("runtime_worker.scheduler.start_failed")


def _shutdown_scheduler(name: str, shutdown_func) -> None:
    try:
        shutdown_func()
    except Exception as exc:
        logger.bind(
            scheduler=name,
            error_type=type(exc).__name__,
        ).warning("runtime_worker.scheduler.stop_failed")


API_SCHEDULERS = (
    ("embedding_worker", start_embedding_worker, shutdown_embedding_worker),
    ("profile_score_scheduler", start_profile_score_scheduler, shutdown_profile_score_scheduler),
    ("archive_worker", start_archive_worker, shutdown_archive_worker),
    ("human_takeover_release_worker", start_human_takeover_release_worker, None),
)

TELEGRAM_SCHEDULERS = (
    ("account_recovery_worker", start_account_recovery_worker, shutdown_account_recovery_worker),
    ("silent_reactivation_scheduler", start_silent_reactivation_scheduler, shutdown_silent_reactivation_scheduler),
    ("notification_sender_worker", start_notification_sender_worker, shutdown_notification_sender_worker),
    ("message_schedule_scheduler", start_message_schedule_scheduler, shutdown_message_schedule_scheduler),
    ("auto_delivery_worker", start_auto_delivery_worker, shutdown_auto_delivery_worker),
    ("fixed_auto_reply_worker", start_fixed_auto_reply_worker, shutdown_fixed_auto_reply_worker),
    ("telegram_user_migration_worker", start_telegram_user_migration_worker, shutdown_telegram_user_migration_worker),
    ("video_reinvite_worker", start_video_reinvite_worker, shutdown_video_reinvite_worker),
    ("call_broadcast_worker", start_call_broadcast_worker, shutdown_call_broadcast_worker),
)

RUNTIME_NURTURE_SCHEDULERS = (
    ("account_recovery_worker", start_account_recovery_worker, shutdown_account_recovery_worker),
    ("message_schedule_scheduler", start_message_schedule_scheduler, shutdown_message_schedule_scheduler),
    ("auto_delivery_worker", start_auto_delivery_worker, shutdown_auto_delivery_worker),
    ("fixed_auto_reply_worker", start_fixed_auto_reply_worker, shutdown_fixed_auto_reply_worker),
    ("telegram_user_migration_worker", start_telegram_user_migration_worker, shutdown_telegram_user_migration_worker),
    ("video_reinvite_worker", start_video_reinvite_worker, shutdown_video_reinvite_worker),
)


def _active_process_role() -> str:
    return set_active_process_role(getattr(settings, "PROCESS_ROLE", "all"))


def _mtproto_runtime_enabled() -> bool:
    return bool(
        getattr(settings, "MTProto_ENABLED", False)
        or getattr(settings, "SESSION_MANAGER_ENABLED", False)
    )


def _shadow_account_snapshot() -> list[tuple[str, str]]:
    from services.telegram_account_manager import telegram_account_manager

    return [
        (str(account_id), "connected")
        for account_id in getattr(telegram_account_manager, "clients", {})
    ]


def request_trace_id(request: Request) -> str:
    trace_id = request.headers.get("x-trace-id") or request.headers.get("x-request-id")
    return trace_id or str(uuid.uuid4())


app = FastAPI(
    title="ERIS API",
    description="Emotional Relationship Intelligence System",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)



async def _run_delayed_telegram_health_check() -> None:
    """Run the expensive all-account probe after session restore has settled."""
    await asyncio.sleep(1800)
    try:
        await run_telegram_account_health_check("startup_delayed")
    except Exception as exc:
        logger.bind(error_type=type(exc).__name__).warning(
            "telegram_account_health.delayed_start_failed"
        )

@app.on_event("startup")
async def start_runtime_workers():
    role = _active_process_role()
    reset_runtime_state(role)
    logger.bind(component="runtime", process_role=role).info("process_role.startup.begin")
    if warn_if_multi_worker(os.environ.get("API_WORKERS", "1"), role):
        logger.bind(
            component="runtime",
            process_role=role,
            api_workers=os.environ.get("API_WORKERS"),
        ).warning("process_role.telegram_runtime.multi_worker_risk")

    if owns_api_workers(role) and not is_shadow_runtime(role):
        for name, start_func, _shutdown_func in API_SCHEDULERS:
            _start_scheduler(name, start_func)

    telegram_ready = True
    if is_shadow_runtime(role):
        mark_runtime_ready(True)
        try:
            await start_shadow_consumer()
        except Exception as exc:
            logger.bind(error_type=type(exc).__name__).warning(
                "runtime_shadow.consumer.start_failed"
            )
    elif is_dedicated_telegram_runtime(role):
        telegram_ready = True
        if _mtproto_runtime_enabled():
            try:
                await session_manager.start()
                logger.info("mtproto.session_manager.started")
                from services.mtproto.inbound_media import schedule_startup_photo_backfill

                schedule_startup_photo_backfill()
            except Exception as exc:
                telegram_ready = False
                logger.bind(error_type=type(exc).__name__).error(
                    "mtproto.session_manager.start_failed"
                )
        if getattr(settings, "CALL_BROADCAST_ENABLED", False):
            try:
                await start_incoming_call_listeners()
            except Exception as exc:
                logger.bind(error_type=type(exc).__name__).error(
                    "call_broadcast.incoming.listeners_start_failed"
                )
        try:
            await start_runtime_consumer()
        except Exception as exc:
            telegram_ready = False
            logger.bind(error_type=type(exc).__name__).error(
                "runtime_consumer.start_failed"
            )
        mark_runtime_ready(telegram_ready)
        if telegram_ready:
            asyncio.create_task(_run_delayed_telegram_health_check())
        for name, start_func, _shutdown_func in RUNTIME_NURTURE_SCHEDULERS:
            _start_scheduler(name, start_func)
        try:
            await restore_pending_reviews_from_db()
        except Exception as exc:
            logger.bind(error_type=type(exc).__name__).warning(
                "call_broadcast.incoming.reviews_restore_failed"
            )
    elif owns_telegram_runtime(role):
        if _mtproto_runtime_enabled():
            try:
                await session_manager.start()
                logger.info("mtproto.session_manager.started")
                asyncio.create_task(_run_delayed_telegram_health_check())
            except Exception as exc:
                telegram_ready = False
                logger.bind(error_type=type(exc).__name__).error(
                    "mtproto.session_manager.start_failed"
                )
        mark_runtime_ready(telegram_ready)
        # Publish live account state before slower listener/scheduler startup.
        # Otherwise the 45-second Redis account shadows expire while hundreds
        # of Telegram listeners are still being initialized, and the admin UI
        # incorrectly reports zero connected accounts.
        try:
            await start_shadow_heartbeat(
                process_role=role,
                runtime_ready_getter=lambda: get_runtime_status()["runtime_ready"],
                account_snapshot_getter=_shadow_account_snapshot,
            )
        except Exception as exc:
            logger.bind(error_type=type(exc).__name__).warning(
                "runtime_shadow.heartbeat.start_failed"
            )
        for name, start_func, _shutdown_func in TELEGRAM_SCHEDULERS:
            _start_scheduler(name, start_func)
        if getattr(settings, "CALL_BROADCAST_ENABLED", False):
            try:
                await start_incoming_call_listeners()
            except Exception as exc:
                logger.bind(error_type=type(exc).__name__).error(
                    "call_broadcast.incoming.listeners_start_failed"
                )
        await restore_pending_reviews_from_db()
    else:
        mark_runtime_ready(True)

    try:
        await start_shadow_heartbeat(
            process_role=role,
            runtime_ready_getter=lambda: get_runtime_status()["runtime_ready"],
            account_snapshot_getter=(
                _shadow_account_snapshot if owns_telegram_runtime(role) else None
            ),
        )
    except Exception as exc:
        logger.bind(error_type=type(exc).__name__).warning(
            "runtime_shadow.heartbeat.start_failed"
        )

    runtime = get_runtime_status()
    logger.bind(
        component="runtime",
        process_role=role,
        runtime_ready=runtime["runtime_ready"],
        owns_api_workers=runtime["owns_api_workers"],
        owns_telegram_runtime=runtime["owns_telegram_runtime"],
    ).info("process_role.startup.ready")


@app.on_event("shutdown")
async def stop_runtime_workers():
    role = normalize_process_role(getattr(settings, "PROCESS_ROLE", "all"))
    logger.bind(component="runtime", process_role=role).info("process_role.shutdown.begin")
    try:
        await stop_shadow_heartbeat()
    except Exception as exc:
        logger.bind(error_type=type(exc).__name__).warning(
            "runtime_shadow.heartbeat.stop_failed"
        )
    try:
        await stop_shadow_consumer()
    except Exception as exc:
        logger.bind(error_type=type(exc).__name__).warning(
            "runtime_shadow.consumer.stop_failed"
        )
    try:
        await stop_runtime_consumer()
    except Exception as exc:
        logger.bind(error_type=type(exc).__name__).warning(
            "runtime_consumer.stop_failed"
        )

    if is_shadow_runtime(role):
        mark_runtime_ready(False)
        logger.bind(component="runtime", process_role=role).info("process_role.shutdown.complete")
        return

    if is_dedicated_telegram_runtime(role):
        try:
            await shutdown_incoming_call_listeners()
        except Exception as exc:
            logger.bind(error_type=type(exc).__name__).warning(
                "call_broadcast.incoming.listeners_shutdown_failed"
            )
        for name, _start_func, shutdown_func in reversed(RUNTIME_NURTURE_SCHEDULERS):
            if shutdown_func is not None:
                _shutdown_scheduler(name, shutdown_func)
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
        try:
            await shutdown_incoming_call_listeners()
        except Exception as exc:
            logger.bind(error_type=type(exc).__name__).warning(
                "call_broadcast.incoming.listeners_shutdown_failed"
            )
        for name, _start_func, shutdown_func in reversed(TELEGRAM_SCHEDULERS):
            if shutdown_func is not None:
                _shutdown_scheduler(name, shutdown_func)
        try:
            await session_manager.stop()
            logger.info("mtproto.session_manager.stopped")
        except Exception as exc:
            logger.bind(error_type=type(exc).__name__).warning(
                "mtproto.session_manager.stop_failed"
            )

    if owns_api_workers(role):
        for name, _start_func, shutdown_func in reversed(API_SCHEDULERS):
            if shutdown_func is not None:
                _shutdown_scheduler(name, shutdown_func)

    mark_runtime_ready(False)
    logger.bind(component="runtime", process_role=role).info("process_role.shutdown.complete")


# Database initialization flag
_db_initialized = False


async def ensure_db_initialized():
    global _db_initialized
    if not _db_initialized:
        await init_db()
        _db_initialized = True
        logger.info("Database initialized")


app.include_router(health_router, tags=["health"])
app.include_router(users_router, prefix="/api/v1/users", tags=["users"])
app.include_router(messages_router, prefix="/api/v1/messages", tags=["messages"])
app.include_router(conversations_router, prefix="/api/v1/conversations", tags=["conversations"])
app.include_router(memories_router, prefix="/api/v1", tags=["memories"])
app.include_router(characters_router, prefix="/api/v1/characters", tags=["characters"])
app.include_router(handoff_router, prefix="/api/v1/handoff", tags=["handoff"])
app.include_router(suspension_router, prefix="/api/v1/suspension", tags=["suspension"])
app.include_router(notifications_router, prefix="/api/v1/notifications", tags=["notifications"])
app.include_router(payments_router, prefix="/api/v1", tags=["payments"])
app.include_router(scripts_router, prefix="/api/v1/scripts", tags=["scripts"])
app.include_router(telegram_router, tags=["telegram"])
app.include_router(telegram_accounts_router, tags=["telegram-accounts"])
app.include_router(mtproto_sessions_router, tags=["mtproto-sessions"])
app.include_router(monitoring_router, tags=["monitoring"])
app.include_router(user_level_router, tags=["user-level"])
app.include_router(message_schedule_router, prefix="/api/v1/message-schedule", tags=["message-schedule"])
app.include_router(auto_delivery_router, prefix="/api/v1/auto-delivery", tags=["auto-delivery"])
app.include_router(archive_router, prefix="/api/v1/archive", tags=["archive"])
app.include_router(intents_router, prefix="/api/v1/intents", tags=["intents"])
app.include_router(realtime_router, tags=["realtime"])
app.include_router(llm_router, prefix="/api/v1", tags=["llm"])
app.include_router(onboarding_router, prefix="/api/v1", tags=["onboarding"])
app.include_router(admin_router, prefix="/api/v1", tags=["admin"])
app.include_router(
    operator_quality_router,
    prefix="/api/v1/operator-quality",
    tags=["operator-quality"],
)
app.include_router(ops_ai_router, prefix="/api/v1/ops-ai", tags=["ops-ai"])
app.include_router(ai_ops_admin_router, prefix="/api/v1/ai-ops/admin", tags=["ai-ops-admin"])
app.include_router(
    ab_experiments_router,
    prefix="/api/v1/ab-experiments",
    tags=["ab-experiments"],
)
app.include_router(open_api_router, prefix="/api/v1/open", tags=["open-api"])
app.include_router(geoip_router, prefix="/api/v1", tags=["geoip"])
app.include_router(device_tokens_router, prefix="/api/v1/device-tokens", tags=["device-tokens"])
app.include_router(metrics_router, tags=["metrics"])
app.include_router(feature_flags_router, prefix="/api/v1", tags=["feature-flags"])
app.include_router(attribution_router, tags=["attribution"])
app.include_router(
    call_broadcast_admin_router,
    prefix="/api/v1/call-broadcast/admin",
    tags=["call-broadcast-admin"],
)
app.include_router(
    fixed_auto_replies_admin_router,
    prefix="/api/v1/fixed-auto-replies/admin",
    tags=["fixed-auto-replies-admin"],
)
app.include_router(
    telegram_user_migration_admin_router,
    prefix="/api/v1/telegram-user-migration/admin",
    tags=["telegram-user-migration-admin"],
)
app.include_router(
    video_reinvite_admin_router,
    prefix="/api/v1/video-reinvite/admin",
    tags=["video-reinvite-admin"],
)

def _resolve_media_upload_dir() -> Path:
    path = Path(settings.MEDIA_UPLOAD_DIR)
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except PermissionError:
        fallback = Path(tempfile.gettempdir()) / "eris-uploads"
        fallback.mkdir(parents=True, exist_ok=True)
        logger.warning(
            "media_upload_dir.permission_denied fallback={} configured={}",
            fallback,
            path,
        )
        return fallback


media_upload_dir = _resolve_media_upload_dir()
app.mount(
    settings.MEDIA_PUBLIC_PATH,
    StaticFiles(directory=media_upload_dir),
    name="uploads",
)

@app.get("/ops/{filename}", include_in_schema=False)
async def ops_static_html(filename: str):
    """只读提供仓库 ``docs/`` 下已审核的 HTML（与 Swagger ``/docs`` 路径区分）。"""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="invalid path")
    if not filename.endswith(".html"):
        raise HTTPException(status_code=404, detail="未找到")
    base = Path(os.environ.get("OPS_DOCS_DIR", "/srv/ops-docs")).resolve()
    path = (base / filename).resolve()
    try:
        path.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid path")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="未找到")
    return FileResponse(path, media_type="text/html; charset=utf-8")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    # Ensure database is initialized on first request
    if not request.url.path.startswith(("/health", "/metrics")):
        await ensure_db_initialized()

    start = time.time()
    trace_id = request_trace_id(request)
    request.state.trace_id = trace_id
    request.state.log_context = {
        "trace_id": trace_id,
        "method": request.method,
        "path": request.url.path,
        "client_ip": request.client.host if request.client else None,
    }
    logger.bind(**request.state.log_context).info("http.request.start")
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.time() - start) * 1000, 2)
        logger.bind(**request.state.log_context, duration_ms=duration_ms).exception("http.request.error")
        raise
    duration_ms = round((time.time() - start) * 1000, 2)
    response.headers["X-Trace-Id"] = trace_id
    logger.bind(
        **request.state.log_context,
        status_code=response.status_code,
        duration_ms=duration_ms,
    ).info("http.request.complete")
    return response


Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
