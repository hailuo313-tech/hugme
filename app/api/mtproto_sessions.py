"""MTProto session management API endpoints for P1-18."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from loguru import logger
from pydantic import BaseModel, Field

from services.mtproto.session_manager import session_manager

router = APIRouter()


class SessionStatusResponse(BaseModel):
    """Response with session status."""

    account_id: str
    status: str
    is_connected: bool
    is_reconnecting: bool
    last_connected_at: str | None
    last_error_at: str | None
    error_message: str | None


class AllSessionsStatusResponse(BaseModel):
    """Response with all sessions status."""

    sessions: List[SessionStatusResponse]
    total: int
    connected_count: int
    reconnecting_count: int


class ReconnectRequest(BaseModel):
    """Request to manually trigger reconnect."""

    account_id: str = Field(..., description="Account ID to reconnect")


class SessionManagerControlResponse(BaseModel):
    """Response for session manager control operations."""

    success: bool
    message: str


@router.get(
    "/api/v1/mtproto/sessions/{account_id}",
    response_model=SessionStatusResponse,
    tags=["mtproto-sessions"],
)
async def get_session_status(account_id: str):
    """Get status of a specific session."""
    try:
        account_uuid = UUID(account_id)
        status = await session_manager.get_session_status(account_uuid)

        if not status:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session for account {account_id} not found",
            )

        return SessionStatusResponse(**status)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid account ID format",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get session status",
        )


@router.get(
    "/api/v1/mtproto/sessions",
    response_model=AllSessionsStatusResponse,
    tags=["mtproto-sessions"],
)
async def get_all_sessions_status():
    """Get status of all sessions."""
    try:
        statuses = await session_manager.get_all_sessions_status()

        connected_count = sum(1 for s in statuses if s["is_connected"])
        reconnecting_count = sum(1 for s in statuses if s["is_reconnecting"])

        return AllSessionsStatusResponse(
            sessions=[SessionStatusResponse(**s) for s in statuses],
            total=len(statuses),
            connected_count=connected_count,
            reconnecting_count=reconnecting_count,
        )
    except Exception as e:
        logger.error(f"Error getting all sessions status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get sessions status",
        )


@router.post(
    "/api/v1/mtproto/sessions/{account_id}/reconnect",
    response_model=SessionManagerControlResponse,
    tags=["mtproto-sessions"],
)
async def trigger_reconnect(account_id: str):
    """Manually trigger reconnection for a specific session."""
    try:
        account_uuid = UUID(account_id)

        # Check if account exists
        from services.telegram_account_manager import telegram_account_manager

        account = await telegram_account_manager.get_account(account_uuid)
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Account {account_id} not found",
            )

        # Trigger reconnect
        session_manager._schedule_reconnect(account_uuid)

        logger.info(f"Manual reconnect triggered for account {account_id}")

        return SessionManagerControlResponse(
            success=True,
            message=f"Reconnect scheduled for account {account_id}",
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid account ID format",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error triggering reconnect: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to trigger reconnect",
        )


@router.delete(
    "/api/v1/mtproto/sessions/{account_id}",
    response_model=SessionManagerControlResponse,
    tags=["mtproto-sessions"],
)
async def delete_session(account_id: str):
    """Delete a session (disconnect and clear)."""
    try:
        account_uuid = UUID(account_id)
        success = await session_manager.delete_session(account_uuid)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session for account {account_id} not found",
            )

        logger.info(f"Session deleted for account {account_id}")

        return SessionManagerControlResponse(
            success=True,
            message=f"Session deleted for account {account_id}",
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid account ID format",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete session",
        )


@router.post(
    "/api/v1/mtproto/sessions/manager/start",
    response_model=SessionManagerControlResponse,
    tags=["mtproto-sessions"],
)
async def start_session_manager():
    """Start the session manager background tasks."""
    try:
        await session_manager.start()
        logger.info("Session manager started via API")

        return SessionManagerControlResponse(
            success=True,
            message="Session manager started",
        )
    except Exception as e:
        logger.error(f"Error starting session manager: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start session manager",
        )


@router.post(
    "/api/v1/mtproto/sessions/manager/stop",
    response_model=SessionManagerControlResponse,
    tags=["mtproto-sessions"],
)
async def stop_session_manager():
    """Stop the session manager background tasks."""
    try:
        await session_manager.stop()
        logger.info("Session manager stopped via API")

        return SessionManagerControlResponse(
            success=True,
            message="Session manager stopped",
        )
    except Exception as e:
        logger.error(f"Error stopping session manager: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to stop session manager",
        )


@router.get(
    "/api/v1/mtproto/sessions/manager/health",
    response_model=dict,
    tags=["mtproto-sessions"],
)
async def get_session_manager_health():
    """Get session manager health status."""
    try:
        return {
            "running": session_manager._running,
            "reconnect_tasks_count": len(session_manager.reconnect_tasks),
            "health_check_task_running": session_manager.health_check_task is not None
            and not session_manager.health_check_task.done(),
        }
    except Exception as e:
        logger.error(f"Error getting session manager health: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get session manager health",
        )