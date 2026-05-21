"""Monitoring API endpoints for P1-20: Account monitoring and metrics."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from loguru import logger
from pydantic import BaseModel, Field

from services.account_monitor import account_monitor

router = APIRouter()


class AccountStatsResponse(BaseModel):
    """Response with account statistics."""

    account_id: str
    phone: str
    status: str
    is_connected: bool
    is_banned: bool
    connection_duration: float
    last_connected_at: str | None
    last_error_at: str | None
    error_message: str | None
    error_rate: float
    send_success_rate: float
    collected_at: str


class SummaryStatsResponse(BaseModel):
    """Response with summary statistics."""

    total_accounts: int
    online_accounts: int
    offline_accounts: int
    banned_accounts: int
    average_success_rate: float
    average_error_rate: float


class SendAttemptRequest(BaseModel):
    """Request to record a send attempt."""

    account_id: str = Field(..., description="Account ID")
    success: bool = Field(..., description="Whether the send was successful")


class MonitorControlResponse(BaseModel):
    """Response for monitor control operations."""

    success: bool
    message: str


@router.get(
    "/api/v1/monitoring/accounts/{account_id}",
    response_model=AccountStatsResponse,
    tags=["monitoring"],
)
async def get_account_stats(account_id: str):
    """Get monitoring statistics for a specific account."""
    try:
        account_uuid = UUID(account_id)
        stats = await account_monitor.get_account_stats(account_uuid)

        if not stats:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Account {account_id} not found or no stats available",
            )

        return AccountStatsResponse(**stats)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid account ID format",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting account stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get account statistics",
        )


@router.get(
    "/api/v1/monitoring/accounts",
    response_model=List[AccountStatsResponse],
    tags=["monitoring"],
)
async def get_all_accounts_stats():
    """Get monitoring statistics for all accounts."""
    try:
        stats = await account_monitor.get_all_accounts_stats()
        return [AccountStatsResponse(**s) for s in stats]
    except Exception as e:
        logger.error(f"Error getting all accounts stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get accounts statistics",
        )


@router.get(
    "/api/v1/monitoring/summary",
    response_model=SummaryStatsResponse,
    tags=["monitoring"],
)
async def get_summary_stats():
    """Get summary statistics for all accounts."""
    try:
        stats = await account_monitor.get_summary_stats()
        return SummaryStatsResponse(**stats)
    except Exception as e:
        logger.error(f"Error getting summary stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get summary statistics",
        )


@router.post(
    "/api/v1/monitoring/send-attempt",
    response_model=MonitorControlResponse,
    tags=["monitoring"],
)
async def record_send_attempt(request: SendAttemptRequest):
    """Record a message send attempt for monitoring."""
    try:
        account_uuid = UUID(request.account_id)
        await account_monitor.record_send_attempt(account_uuid, request.success)

        logger.info(f"Recorded send attempt for account {request.account_id}: success={request.success}")

        return MonitorControlResponse(
            success=True,
            message=f"Send attempt recorded for account {request.account_id}",
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid account ID format",
        )
    except Exception as e:
        logger.error(f"Error recording send attempt: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record send attempt",
        )


@router.post(
    "/api/v1/monitoring/start",
    response_model=MonitorControlResponse,
    tags=["monitoring"],
)
async def start_monitor():
    """Start the account monitoring service."""
    try:
        await account_monitor.start()
        logger.info("Account monitor started via API")

        return MonitorControlResponse(
            success=True,
            message="Account monitor started",
        )
    except Exception as e:
        logger.error(f"Error starting monitor: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start account monitor",
        )


@router.post(
    "/api/v1/monitoring/stop",
    response_model=MonitorControlResponse,
    tags=["monitoring"],
)
async def stop_monitor():
    """Stop the account monitoring service."""
    try:
        await account_monitor.stop()
        logger.info("Account monitor stopped via API")

        return MonitorControlResponse(
            success=True,
            message="Account monitor stopped",
        )
    except Exception as e:
        logger.error(f"Error stopping monitor: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to stop account monitor",
        )


@router.get(
    "/api/v1/monitoring/health",
    response_model=dict,
    tags=["monitoring"],
)
async def get_monitor_health():
    """Get account monitor health status."""
    try:
        return {
            "running": account_monitor._running,
            "metrics_port": account_monitor.metrics_port,
            "collection_interval": account_monitor.collection_interval,
            "collection_task_running": account_monitor._collection_task is not None
            and not account_monitor._collection_task.done(),
            "tracked_accounts_count": len(account_monitor.account_stats),
        }
    except Exception as e:
        logger.error(f"Error getting monitor health: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get monitor health",
        )