"""Message schedule API endpoints for P3-13: Redis pending queue + send_at."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel

from services.message_schedule_service import (
    add_scheduled_message,
    get_scheduler_status,
    run_one_tick,
)

router = APIRouter()


class AddMessageRequest(BaseModel):
    user_id: str
    external_user_id: str
    message_type: str
    content: str
    platform: str = "telegram_real_user"
    account_id: Optional[str] = None
    chat_id: Optional[int] = None
    send_at: Optional[datetime] = None
    priority: int = 0
    metadata: Optional[dict] = None
    trace_id: Optional[str] = None


class AddMessageResponse(BaseModel):
    message_id: str
    status: str
    message: str


@router.post("/test/add-message", response_model=AddMessageResponse)
async def add_message(request: Request, req: AddMessageRequest):
    """Add a message to the pending queue (test endpoint)."""
    trace_id = request.state.trace_id
    log = logger.bind(trace_id=trace_id)

    try:
        message_id = await add_scheduled_message(
            user_id=req.user_id,
            external_user_id=req.external_user_id,
            message_type=req.message_type,
            content=req.content,
            platform=req.platform,
            account_id=req.account_id,
            chat_id=req.chat_id,
            send_at=req.send_at,
            priority=req.priority,
            metadata=req.metadata,
            trace_id=req.trace_id or trace_id,
        )

        log.bind(message_id=message_id).info("message_schedule.api.add_message.success")

        return AddMessageResponse(
            message_id=message_id,
            status="success",
            message=f"Message added to queue with ID: {message_id}",
        )
    except Exception as e:
        log.error(f"message_schedule.api.add_message.error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class TickResponse(BaseModel):
    status: str
    stats: dict
    message: str


@router.post("/test/tick", response_model=TickResponse)
async def tick(request: Request):
    """Manually trigger one tick of the message schedule worker (test endpoint)."""
    trace_id = request.state.trace_id
    log = logger.bind(trace_id=trace_id)

    try:
        stats = await run_one_tick(trace_id=trace_id)

        log.bind(stats=stats).info("message_schedule.api.tick.success")

        return TickResponse(
            status="success",
            stats=stats,
            message=f"Tick completed. Claimed: {stats['claimed']}, Sent: {stats['sent']}, Failed: {stats['failed']}",
        )
    except Exception as e:
        log.error(f"message_schedule.api.tick.error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class StatusResponse(BaseModel):
    status: str
    scheduler: dict
    message: str


@router.get("/test/status", response_model=StatusResponse)
async def get_status(request: Request):
    """Get message schedule scheduler status (test endpoint)."""
    trace_id = request.state.trace_id
    log = logger.bind(trace_id=trace_id)

    try:
        scheduler_status = get_scheduler_status()

        log.bind(scheduler_status=scheduler_status).info("message_schedule.api.status.success")

        return StatusResponse(
            status="success",
            scheduler=scheduler_status,
            message=f"Scheduler running: {scheduler_status['running']}",
        )
    except Exception as e:
        log.error(f"message_schedule.api.status.error: {e}")
        raise HTTPException(status_code=500, detail=str(e))