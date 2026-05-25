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
from core.database import init_db
from core.config import settings
from services.mtproto.session_manager import session_manager
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


@app.on_event("startup")
async def start_runtime_workers():
    _start_scheduler("embedding_worker", start_embedding_worker)
    _start_scheduler("profile_score_scheduler", start_profile_score_scheduler)
    _start_scheduler(
        "silent_reactivation_scheduler",
        start_silent_reactivation_scheduler,
    )
    _start_scheduler("notification_sender_worker", start_notification_sender_worker)
    _start_scheduler("message_schedule_scheduler", start_message_schedule_scheduler)
    _start_scheduler("auto_delivery_worker", start_auto_delivery_worker)
    _start_scheduler("archive_worker", start_archive_worker)

    mtproto_runtime_enabled = bool(
        getattr(settings, "MTProto_ENABLED", False)
        or getattr(settings, "SESSION_MANAGER_ENABLED", False)
    )
    if mtproto_runtime_enabled:
        try:
            await session_manager.start()
            logger.info("mtproto.session_manager.started")
        except Exception as exc:
            logger.bind(error_type=type(exc).__name__).error(
                "mtproto.session_manager.start_failed"
            )


@app.on_event("shutdown")
async def stop_runtime_workers():
    _shutdown_scheduler("archive_worker", shutdown_archive_worker)
    _shutdown_scheduler("auto_delivery_worker", shutdown_auto_delivery_worker)
    _shutdown_scheduler("message_schedule_scheduler", shutdown_message_schedule_scheduler)
    _shutdown_scheduler("notification_sender_worker", shutdown_notification_sender_worker)
    _shutdown_scheduler(
        "silent_reactivation_scheduler",
        shutdown_silent_reactivation_scheduler,
    )
    _shutdown_scheduler("profile_score_scheduler", shutdown_profile_score_scheduler)
    _shutdown_scheduler("embedding_worker", shutdown_embedding_worker)

    try:
        await session_manager.stop()
        logger.info("mtproto.session_manager.stopped")
    except Exception as exc:
        logger.bind(error_type=type(exc).__name__).warning(
            "mtproto.session_manager.stop_failed"
        )


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
