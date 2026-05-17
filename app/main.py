import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
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
from api.realtime import router as realtime_router
from api.llm import router as llm_router
from api.onboarding import router as onboarding_router
from api.admin import router as admin_router
from api.operator_quality import router as operator_quality_router
from api.ops_ai import router as ops_ai_router
from api.ab_experiments import router as ab_experiments_router
from core.database import init_db
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


def request_trace_id(request: Request) -> str:
    trace_id = request.headers.get("x-trace-id") or request.headers.get("x-request-id")
    return trace_id or str(uuid.uuid4())


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ERIS starting up...")
    await init_db()
    logger.info("Database connected")
    start_silent_reactivation_scheduler()
    start_embedding_worker()
    start_profile_score_scheduler()
    start_notification_sender_worker()
    try:
        yield
    finally:
        shutdown_profile_score_scheduler()
        shutdown_notification_sender_worker()
        shutdown_embedding_worker()
        shutdown_silent_reactivation_scheduler()
        logger.info("ERIS shutting down...")


app = FastAPI(
    title="ERIS API",
    description="Emotional Relationship Intelligence System",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
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


app.include_router(health_router, tags=["health"])
app.include_router(users_router, prefix="/api/v1/users", tags=["users"])
app.include_router(messages_router, prefix="/api/v1/messages", tags=["messages"])
app.include_router(conversations_router, prefix="/api/v1/conversations", tags=["conversations"])
app.include_router(memories_router, prefix="/api/v1", tags=["memories"])
app.include_router(characters_router, prefix="/api/v1/characters", tags=["characters"])
app.include_router(handoff_router, prefix="/api/v1/handoff", tags=["handoff"])
app.include_router(notifications_router, prefix="/api/v1/notifications", tags=["notifications"])
app.include_router(payments_router, prefix="/api/v1", tags=["payments"])
app.include_router(scripts_router, prefix="/api/v1/scripts", tags=["scripts"])
app.include_router(telegram_router, tags=["telegram"])
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
app.include_router(
    ab_experiments_router,
    prefix="/api/v1/ab-experiments",
    tags=["ab-experiments"],
)

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
