"""Auto-delivery worker API endpoints for P3-15: B/C/D auto-delivery testing."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel

from services.auto_delivery_worker import (
    get_scheduler_status,
    reinit_account_pool,
    run_one_tick,
)

router = APIRouter()


class TickResponse(BaseModel):
    status: str
    stats: dict
    message: str


@router.post("/test/tick", response_model=TickResponse)
async def tick(request: Request):
    """Manually trigger one tick of the auto-delivery worker (test endpoint)."""
    trace_id = request.state.trace_id
    log = logger.bind(trace_id=trace_id)

    try:
        stats = await run_one_tick(trace_id=trace_id)

        log.bind(stats=stats).info("auto_delivery.api.tick.success")

        return TickResponse(
            status="success",
            stats=stats,
            message=f"Tick completed. Claimed: {stats['claimed']}, Sent: {stats['sent']}, Failed: {stats['failed']}",
        )
    except Exception as e:
        log.error(f"auto_delivery.api.tick.error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class StatusResponse(BaseModel):
    status: str
    scheduler: dict
    message: str


@router.get("/test/status", response_model=StatusResponse)
async def get_status(request: Request):
    """Get auto-delivery worker scheduler status (test endpoint)."""
    trace_id = request.state.trace_id
    log = logger.bind(trace_id=trace_id)

    try:
        scheduler_status = get_scheduler_status()

        log.bind(scheduler_status=scheduler_status).info("auto_delivery.api.status.success")

        return StatusResponse(
            status="success",
            scheduler=scheduler_status,
            message=f"Scheduler running: {scheduler_status['running']}, AccountPool initialized: {scheduler_status['account_pool_initialized']}",
        )
    except Exception as e:
        log.error(f"auto_delivery.api.status.error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ReinitResponse(BaseModel):
    status: str
    success: bool
    message: str


@router.post("/test/reinit-account-pool", response_model=ReinitResponse)
async def reinit_pool(request: Request):
    """Reinitialize AccountPool (test endpoint)."""
    trace_id = request.state.trace_id
    log = logger.bind(trace_id=trace_id)

    try:
        success = await reinit_account_pool()

        log.bind(success=success).info("auto_delivery.api.reinit.success")

        return ReinitResponse(
            status="success",
            success=success,
            message="AccountPool reinitialized successfully" if success else "Failed to reinitialize AccountPool",
        )
    except Exception as e:
        log.error(f"auto_delivery.api.reinit.error: {e}")
        raise HTTPException(status_code=500, detail=str(e))