from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import require_operator
from core.database import get_db
from services.link_attribution import (
    ALLOWED_EVENT_TYPES,
    create_attribution_link as insert_attribution_link,
    record_attribution_event,
    tracking_url,
)

router = APIRouter()


class AttributionLinkCreate(BaseModel):
    destination_url: str
    user_id: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    script_hit_id: str | None = None
    script_template_id: str | None = None
    campaign_id: str | None = None
    platform: str | None = None
    persona_slug: str | None = None
    intent: str | None = None
    country_code: str | None = None
    age: int | None = Field(default=None, ge=0, le=120)
    user_level: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("destination_url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("destination_url must be an absolute http(s) URL")
        return value


class AttributionLinkResponse(BaseModel):
    tracking_id: str
    tracking_url: str
    destination_url: str


class AttributionEventCreate(BaseModel):
    tracking_id: str
    event_type: str
    user_id: str | None = None
    app_user_id: str | None = None
    country_code: str | None = None
    age: int | None = Field(default=None, ge=0, le=120)
    user_level: str | None = None
    device_os: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_type")
    @classmethod
    def _event_type(cls, value: str) -> str:
        if value not in ALLOWED_EVENT_TYPES - {"click", "payment"}:
            raise ValueError("event_type must be download_page, download, or app_register")
        return value


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else None


@router.post(
    "/api/v1/attribution/links",
    response_model=AttributionLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_attribution_link(
    data: AttributionLinkCreate,
    request: Request,
    _: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    tracking_id = await insert_attribution_link(
        db,
        destination_url=data.destination_url,
        user_id=data.user_id,
        conversation_id=data.conversation_id,
        message_id=data.message_id,
        script_hit_id=data.script_hit_id,
        script_template_id=data.script_template_id,
        campaign_id=data.campaign_id,
        platform=data.platform,
        persona_slug=data.persona_slug,
        intent=data.intent,
        country_code=data.country_code,
        age=data.age,
        user_level=data.user_level,
        metadata=data.metadata,
    )
    await db.commit()
    base = str(request.base_url).rstrip("/")
    return AttributionLinkResponse(
        tracking_id=tracking_id,
        tracking_url=tracking_url(base, tracking_id),
        destination_url=data.destination_url,
    )


@router.get("/r/{tracking_id}", include_in_schema=False)
async def redirect_tracking_link(
    tracking_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            text(
                """
                SELECT
                    destination_url, user_id, country_code, age, user_level
                FROM attribution_links
                WHERE tracking_id = :tracking_id
                """
            ),
            {"tracking_id": tracking_id},
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="tracking link not found")

    await record_attribution_event(
        db,
        tracking_id=tracking_id,
        event_type="click",
        user_id=row[1],
        country_code=row[2],
        age=row[3],
        user_level=row[4],
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        referrer=request.headers.get("referer"),
    )
    await db.commit()
    return RedirectResponse(url=row[0], status_code=302)


@router.post("/api/v1/attribution/events", status_code=status.HTTP_202_ACCEPTED)
async def record_app_attribution_event(
    data: AttributionEventCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await record_attribution_event(
        db,
        tracking_id=data.tracking_id,
        event_type=data.event_type,
        user_id=data.user_id,
        app_user_id=data.app_user_id,
        country_code=data.country_code,
        age=data.age,
        user_level=data.user_level,
        device_os=data.device_os,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        referrer=request.headers.get("referer"),
        metadata_json=json.dumps(data.metadata, ensure_ascii=False),
    )
    await db.commit()
    return {"status": "accepted", "tracking_id": data.tracking_id}


@router.get("/api/v1/admin/attribution/summary")
async def admin_attribution_summary(
    days: int = Query(7, ge=1, le=90),
    _: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    params = {"days": days}
    overview = (
        await db.execute(
            text(
                """
                WITH events AS (
                    SELECT *
                    FROM attribution_events
                    WHERE created_at >= NOW() - (:days || ' days')::interval
                )
                SELECT
                    COUNT(DISTINCT tracking_id) FILTER (WHERE event_type = 'click') AS clicked_links,
                    COUNT(DISTINCT user_id) FILTER (WHERE event_type = 'click') AS click_users,
                    COUNT(DISTINCT user_id) FILTER (WHERE event_type = 'download') AS download_users,
                    COUNT(DISTINCT COALESCE(app_user_id, user_id::text)) FILTER (WHERE event_type = 'app_register') AS register_users,
                    COUNT(DISTINCT user_id) FILTER (WHERE event_type = 'payment') AS paid_users,
                    COALESCE(SUM(amount_cents) FILTER (WHERE event_type = 'payment'), 0) AS revenue_cents
                FROM events
                """
            ),
            params,
        )
    ).fetchone()
    country_rows = (
        await db.execute(
            text(
                """
                SELECT COALESCE(country_code, 'UNKNOWN') AS country_code,
                       COUNT(*) FILTER (WHERE event_type = 'click') AS clicks,
                       COUNT(*) FILTER (WHERE event_type = 'payment') AS payments
                FROM attribution_events
                WHERE created_at >= NOW() - (:days || ' days')::interval
                GROUP BY 1
                ORDER BY clicks DESC, payments DESC
                LIMIT 10
                """
            ),
            params,
        )
    ).fetchall()
    script_rows = (
        await db.execute(
            text(
                """
                SELECT
                    COALESCE(l.script_hit_id, l.script_template_id::text, 'unknown') AS script_key,
                    COUNT(*) FILTER (WHERE e.event_type = 'click') AS clicks,
                    COUNT(*) FILTER (WHERE e.event_type = 'download') AS downloads,
                    COUNT(*) FILTER (WHERE e.event_type = 'app_register') AS registrations,
                    COUNT(*) FILTER (WHERE e.event_type = 'payment') AS payments,
                    COALESCE(SUM(e.amount_cents) FILTER (WHERE e.event_type = 'payment'), 0) AS revenue_cents
                FROM attribution_events e
                LEFT JOIN attribution_links l ON l.tracking_id = e.tracking_id
                WHERE e.created_at >= NOW() - (:days || ' days')::interval
                GROUP BY 1
                ORDER BY payments DESC, registrations DESC, clicks DESC
                LIMIT 10
                """
            ),
            params,
        )
    ).fetchall()

    def value(row: Any, idx: int, default: Any = 0) -> Any:
        try:
            return row[idx]
        except Exception:
            return default

    clicks = int(value(overview, 1) or 0)
    downloads = int(value(overview, 2) or 0)
    registrations = int(value(overview, 3) or 0)
    payments = int(value(overview, 4) or 0)
    return {
        "days": days,
        "overview": {
            "clicked_links": int(value(overview, 0) or 0),
            "click_users": clicks,
            "download_users": downloads,
            "register_users": registrations,
            "paid_users": payments,
            "revenue_cents": int(value(overview, 5) or 0),
            "download_rate": downloads / clicks if clicks else 0,
            "register_rate": registrations / clicks if clicks else 0,
            "payment_rate": payments / clicks if clicks else 0,
        },
        "countries": [
            {"country_code": r[0], "clicks": int(r[1] or 0), "payments": int(r[2] or 0)}
            for r in country_rows
        ],
        "top_scripts": [
            {
                "script_key": r[0],
                "clicks": int(r[1] or 0),
                "downloads": int(r[2] or 0),
                "registrations": int(r[3] or 0),
                "payments": int(r[4] or 0),
                "revenue_cents": int(r[5] or 0),
            }
            for r in script_rows
        ],
    }
