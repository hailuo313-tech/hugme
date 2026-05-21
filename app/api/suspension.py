"""Suspension API endpoints for P3-16: S/A hang + draft with Top3 scripts."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import require_operator
from core.database import get_db
from services.suspension_service import (
    create_handoff_draft,
    get_draft_with_countdown,
    suspend_sa_message,
)

router = APIRouter()


class SuspendRequest(BaseModel):
    conversation_id: str = Field(..., description="Conversation ID")
    query_text: str = Field(..., description="Query text for script search")
    trigger_reason: str = Field(default="SA_LEVEL_AUTO_SUSPEND", description="Reason for suspension")
    countdown_seconds: int = Field(default=120, ge=30, le=300, description="Countdown duration in seconds")


class CreateDraftRequest(BaseModel):
    task_id: str = Field(..., description="Handoff task ID")
    query_text: str = Field(..., description="Query text for script search")
    countdown_seconds: int = Field(default=120, ge=30, le=300, description="Countdown duration in seconds")


@router.post("/suspend")
async def suspend_message(
    request: SuspendRequest,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    """Suspend message for S/A level user and create handoff task with draft."""
    trace_id = getattr(request.state, "trace_id", None)
    log = logger.bind(trace_id=trace_id)

    try:
        result = await suspend_sa_message(
            db=db,
            conversation_id=request.conversation_id,
            query_text=request.query_text,
            trigger_reason=request.trigger_reason,
            countdown_seconds=request.countdown_seconds,
            trace_id=trace_id,
        )

        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("reason"))

        log.bind(result=result).info("suspension.api.suspend.success")
        return result

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"suspension.api.suspend.error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/draft/create")
async def create_draft(
    request: CreateDraftRequest,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    """Create or update draft for handoff task with Top3 script recommendations."""
    trace_id = getattr(request.state, "trace_id", None)
    log = logger.bind(trace_id=trace_id)

    try:
        result = await create_handoff_draft(
            db=db,
            task_id=request.task_id,
            query_text=request.query_text,
            countdown_seconds=request.countdown_seconds,
            trace_id=trace_id,
        )

        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("reason"))

        log.bind(result=result).info("suspension.api.create_draft.success")
        return result

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"suspension.api.create_draft.error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/draft/{task_id}")
async def get_draft(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    """Get draft information with remaining countdown for handoff task."""
    trace_id = getattr(request.state, "trace_id", None)
    log = logger.bind(trace_id=trace_id)

    try:
        result = await get_draft_with_countdown(
            db=db,
            task_id=task_id,
            trace_id=trace_id,
        )

        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("reason"))

        log.bind(result=result).info("suspension.api.get_draft.success")
        return result

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"suspension.api.get_draft.error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Test endpoints (without operator requirement for testing)


@router.post("/test/suspend")
async def test_suspend(
    request: SuspendRequest,
    req: Request,
    db: AsyncSession = Depends(get_db),
):
    """Test endpoint for suspend (no operator requirement)."""
    trace_id = req.state.trace_id
    log = logger.bind(trace_id=trace_id)

    try:
        result = await suspend_sa_message(
            db=db,
            conversation_id=request.conversation_id,
            query_text=request.query_text,
            trigger_reason=request.trigger_reason,
            countdown_seconds=request.countdown_seconds,
            trace_id=trace_id,
        )

        log.bind(result=result).info("suspension.api.test_suspend.success")
        return result

    except Exception as e:
        log.error(f"suspension.api.test_suspend.error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test/draft/create")
async def test_create_draft(
    request: CreateDraftRequest,
    req: Request,
    db: AsyncSession = Depends(get_db),
):
    """Test endpoint for create draft (no operator requirement)."""
    trace_id = req.state.trace_id
    log = logger.bind(trace_id=trace_id)

    try:
        result = await create_handoff_draft(
            db=db,
            task_id=request.task_id,
            query_text=request.query_text,
            countdown_seconds=request.countdown_seconds,
            trace_id=trace_id,
        )

        log.bind(result=result).info("suspension.api.test_create_draft.success")
        return result

    except Exception as e:
        log.error(f"suspension.api.test_create_draft.error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/test/draft/{task_id}")
async def test_get_draft(
    task_id: str,
    req: Request,
    db: AsyncSession = Depends(get_db),
):
    """Test endpoint for get draft (no operator requirement)."""
    trace_id = req.state.trace_id
    log = logger.bind(trace_id=trace_id)

    try:
        result = await get_draft_with_countdown(
            db=db,
            task_id=task_id,
            trace_id=trace_id,
        )

        log.bind(result=result).info("suspension.api.test_get_draft.success")
        return result

    except Exception as e:
        log.error(f"suspension.api.test_get_draft.error: {e}")
        raise HTTPException(status_code=500, detail=str(e))