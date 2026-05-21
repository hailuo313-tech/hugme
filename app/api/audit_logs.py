"""P1-16 audit log query API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import require_operator
from core.database import get_db
from services.audit_log_service import RECENT_AUDIT_LIMIT, get_recent_audit_logs


router = APIRouter()


@router.get("/audit-logs/recent")
async def recent_audit_logs(
    limit: int = Query(RECENT_AUDIT_LIMIT, ge=1, le=RECENT_AUDIT_LIMIT),
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
) -> dict[str, object]:
    rows = await get_recent_audit_logs(db, limit=limit)
    return {"limit": limit, "items": rows}
