"""Archive API endpoints for P3-18: Async premium chat archiving."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field

from services.archive_service import (
    archive_message_async,
    get_conversation_script_hits,
    get_scheduler_status,
    run_one_tick,
)

router = APIRouter()


class ArchiveRequest(BaseModel):
    conversation_id: str = Field(..., description="Conversation ID")
    message_id: str = Field(..., description="Message ID")
    script_hit_id: str = Field(..., description="Script hit ID")
    hook: str = Field(default="archive", description="Script hook name")
    user_level: str = Field(default="C", description="User level")
    platform: str = Field(default="telegram", description="Platform")


class ArchiveResponse(BaseModel):
    status: str
    message: str
    archived: bool = False


@router.post("/archive")
async def archive_message_endpoint(
    request: Request,
    req: ArchiveRequest,
):
    """Archive a message asynchronously (non-blocking)."""
    trace_id = request.state.trace_id
    log = logger.bind(trace_id=trace_id)

    try:
        # Create async task without blocking
        task = await archive_message_async(
            conversation_id=req.conversation_id,
            message_id=req.message_id,
            script_hit_id=req.script_hit_id,
            hook=req.hook,
            user_level=req.user_level,
            platform=req.platform,
            trace_id=trace_id,
        )

        log.bind(
            conversation_id=req.conversation_id,
            message_id=req.message_id,
        ).info("archive.api.archive.async_started")

        return ArchiveResponse(
            status="async_started",
            message="Archive task started in background (non-blocking)",
            archived=True,
        )
    except Exception as e:
        log.error(f"archive.api.archive.error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class TickResponse(BaseModel):
    status: str
    stats: dict
    message: str


@router.post("/test/tick")
async def tick(request: Request):
    """Manually trigger one tick of the archive worker (test endpoint)."""
    trace_id = request.state.trace_id
    log = logger.bind(trace_id=trace_id)

    try:
        stats = await run_one_tick(trace_id=trace_id)

        log.bind(stats=stats).info("archive.api.tick.success")

        return TickResponse(
            status="success",
            stats=stats,
            message=f"Tick completed. Claimed: {stats['claimed']}, Archived: {stats['archived']}, Failed: {stats['failed']}",
        )
    except Exception as e:
        log.error(f"archive.api.tick.error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class StatusResponse(BaseModel):
    status: str
    scheduler: dict
    message: str


@router.get("/test/status")
async def get_status(request: Request):
    """Get archive worker scheduler status (test endpoint)."""
    trace_id = request.state.trace_id
    log = logger.bind(trace_id=trace_id)

    try:
        scheduler_status = get_scheduler_status()

        log.bind(scheduler_status=scheduler_status).info("archive.api.status.success")

        return StatusResponse(
            status="success",
            scheduler=scheduler_status,
            message=f"Scheduler running: {scheduler_status['running']}",
        )
    except Exception as e:
        log.error(f"archive.api.status.error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ConversationHitsResponse(BaseModel):
    status: str
    conversation_id: str
    hits: list
    count: int
    message: str


@router.get("/conversation/{conversation_id}/hits")
async def get_conversation_hits(
    conversation_id: str,
    request: Request,
    limit: int = 100,
):
    """Get script hit records for a conversation."""
    trace_id = request.state.trace_id
    log = logger.bind(trace_id=trace_id)

    try:
        hits = await get_conversation_script_hits(
            conversation_id=conversation_id,
            limit=limit,
            trace_id=trace_id,
        )

        log.bind(
            conversation_id=conversation_id,
            hits_count=len(hits),
        ).info("archive.api.get_hits.success")

        return ConversationHitsResponse(
            status="success",
            conversation_id=conversation_id,
            hits=hits,
            count=len(hits),
            message=f"Found {len(hits)} script hit records",
        )
    except Exception as e:
        log.error(f"archive.api.get_hits.error: {e}")
        raise HTTPException(status_code=500, detail=str(e))