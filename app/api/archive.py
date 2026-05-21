"""Archive API endpoints for P3-18: Async premium chat archiving."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field

from services.archive_service import (
    archive_message_async,
    get_conversation_script_hits,
    get_premium_chat_trace,
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


class PremiumChatTraceResponse(BaseModel):
    status: str
    conversation_id: str
    eligible: bool
    conversation: dict | None = None
    messages: list = Field(default_factory=list)
    script_hits: list = Field(default_factory=list)
    traceability: dict = Field(default_factory=dict)
    reason: str | None = None
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


@router.get("/premium-chat/{conversation_id}/trace")
async def get_premium_chat_trace_endpoint(
    conversation_id: str,
    request: Request,
    limit: int = 100,
):
    """P3-19: query S/A premium chat with every script_hit trajectory."""
    trace_id = request.state.trace_id
    log = logger.bind(trace_id=trace_id)

    try:
        trace = await get_premium_chat_trace(
            conversation_id=conversation_id,
            limit=limit,
            trace_id=trace_id,
        )
        if not trace.get("found"):
            raise HTTPException(status_code=404, detail=trace.get("reason"))
        if not trace.get("eligible"):
            raise HTTPException(status_code=403, detail=trace.get("reason"))

        log.bind(
            conversation_id=conversation_id,
            hit_count=len(trace.get("script_hits", [])),
            complete_8_hooks=trace.get("traceability", {}).get("complete_8_hooks"),
        ).info("archive.api.premium_trace.success")

        return PremiumChatTraceResponse(
            status="success",
            conversation_id=conversation_id,
            eligible=True,
            conversation=trace.get("conversation"),
            messages=trace.get("messages", []),
            script_hits=trace.get("script_hits", []),
            traceability=trace.get("traceability", {}),
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"archive.api.premium_trace.error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
