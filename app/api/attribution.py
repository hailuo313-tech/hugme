from __future__ import annotations

from datetime import date as date_type, timedelta
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
    sender_account_id: str | None = None
    scene_step: str | None = None
    script_category: str | None = None
    is_t1_country: bool | None = None
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
        if value not in ALLOWED_EVENT_TYPES - {"link_exposed", "click", "payment"}:
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
        sender_account_id=data.sender_account_id,
        scene_step=data.scene_step,
        script_category=data.script_category,
        is_t1_country=data.is_t1_country,
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
    if data.event_type == "app_register" and data.app_user_id:
        await db.execute(
            text(
                """
                INSERT INTO app_user_attribution_bindings (
                    app_user_id, telegram_user_id, tracking_id, registered_at, metadata
                )
                VALUES (
                    :app_user_id, :telegram_user_id, :tracking_id, NOW(), CAST(:metadata AS JSONB)
                )
                ON CONFLICT (app_user_id) DO UPDATE
                SET telegram_user_id = COALESCE(app_user_attribution_bindings.telegram_user_id, EXCLUDED.telegram_user_id),
                    tracking_id = COALESCE(app_user_attribution_bindings.tracking_id, EXCLUDED.tracking_id),
                    registered_at = COALESCE(app_user_attribution_bindings.registered_at, EXCLUDED.registered_at),
                    metadata = app_user_attribution_bindings.metadata || EXCLUDED.metadata
                """
            ),
            {
                "app_user_id": data.app_user_id,
                "telegram_user_id": data.user_id,
                "tracking_id": data.tracking_id,
                "metadata": json.dumps(data.metadata, ensure_ascii=False),
            },
        )
    await db.commit()
    return {"status": "accepted", "tracking_id": data.tracking_id}


@router.get("/api/v1/admin/attribution/summary")
async def admin_attribution_summary(
    days: int = Query(7, ge=1, le=90),
    selected_date: date_type | None = Query(default=None, alias="date"),
    _: dict = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    if selected_date:
        params = {
            "days": days,
            "start_at": selected_date,
            "end_at": selected_date + timedelta(days=1),
        }
        link_window = "COALESCE(sent_at, created_at) >= :start_at AND COALESCE(sent_at, created_at) < :end_at"
        event_window = "created_at >= :start_at AND created_at < :end_at"
        event_window_alias = "e.created_at >= :start_at AND e.created_at < :end_at"
        user_window = "u.created_at >= :start_at AND u.created_at < :end_at"
    else:
        params = {"days": days}
        link_window = "COALESCE(sent_at, created_at) >= NOW() - (:days || ' days')::interval"
        event_window = "created_at >= NOW() - (:days || ' days')::interval"
        event_window_alias = "e.created_at >= NOW() - (:days || ' days')::interval"
        user_window = "u.created_at >= NOW() - (:days || ' days')::interval"
    overview = (
        await db.execute(
            text(
                f"""
                WITH links AS (
                    SELECT *
                    FROM attribution_links
                    WHERE {link_window}
                ),
                events AS (
                    SELECT e.*
                    FROM attribution_events e
                    WHERE {event_window_alias}
                ),
                first_events AS (
                    SELECT
                        tracking_id,
                        MIN(created_at) FILTER (WHERE event_type = 'click') AS first_click_at,
                        MIN(created_at) FILTER (WHERE event_type = 'download_page') AS first_download_page_at,
                        MIN(created_at) FILTER (WHERE event_type = 'download') AS first_download_at,
                        MIN(created_at) FILTER (WHERE event_type = 'app_register') AS first_register_at,
                        MIN(created_at) FILTER (WHERE event_type = 'payment') AS first_payment_at
                    FROM attribution_events
                    WHERE {event_window}
                    GROUP BY tracking_id
                )
                SELECT
                    COUNT(DISTINCT l.tracking_id) AS sent_links,
                    COUNT(DISTINCT l.user_id) AS sent_users,
                    COUNT(DISTINCT e.tracking_id) FILTER (WHERE e.event_type = 'link_exposed') AS exposed_links,
                    COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_type = 'link_exposed') AS exposed_users,
                    COUNT(DISTINCT e.tracking_id) FILTER (WHERE e.event_type = 'click') AS clicked_links,
                    COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_type = 'click') AS click_users,
                    COUNT(*) FILTER (WHERE e.event_type = 'click') AS click_events,
                    COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_type = 'download_page') AS download_page_users,
                    COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_type = 'download') AS download_users,
                    COUNT(DISTINCT COALESCE(e.app_user_id, e.user_id::text)) FILTER (WHERE e.event_type = 'app_register') AS register_users,
                    COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_type = 'payment') AS paid_users,
                    COALESCE(SUM(e.amount_cents) FILTER (WHERE e.event_type = 'payment'), 0) AS revenue_cents,
                    COUNT(DISTINCT e.user_id) FILTER (
                        WHERE e.event_type = 'payment' AND e.user_level IN ('A', 'S')
                    ) AS upgraded_paid_users,
                    COUNT(DISTINCT e.user_id) FILTER (
                        WHERE e.event_type = 'click' AND e.created_at::date = CURRENT_DATE
                    ) AS today_click_users,
                    COALESCE(AVG(EXTRACT(EPOCH FROM (f.first_click_at - COALESCE(l.sent_at, l.created_at)))) FILTER (
                        WHERE f.first_click_at IS NOT NULL
                    ), 0) AS avg_sent_to_click_seconds,
                    COALESCE(AVG(EXTRACT(EPOCH FROM (f.first_register_at - f.first_click_at))) FILTER (
                        WHERE f.first_click_at IS NOT NULL AND f.first_register_at IS NOT NULL
                    ), 0) AS avg_click_to_register_seconds,
                    COALESCE(AVG(EXTRACT(EPOCH FROM (f.first_payment_at - f.first_click_at))) FILTER (
                        WHERE f.first_click_at IS NOT NULL AND f.first_payment_at IS NOT NULL
                    ), 0) AS avg_click_to_payment_seconds
                FROM links l
                LEFT JOIN events e ON e.tracking_id = l.tracking_id
                LEFT JOIN first_events f ON f.tracking_id = l.tracking_id
                """
            ),
            params,
        )
    ).fetchone()

    async def fetch_rows(sql: str) -> list[Any]:
        return list((await db.execute(text(sql), params)).fetchall())

    dimension_sql = f"""
        SELECT
            {{key_expr}} AS key,
            COUNT(*) FILTER (WHERE e.event_type = 'link_exposed') AS exposures,
            COUNT(*) FILTER (WHERE e.event_type = 'click') AS clicks,
            COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_type = 'click') AS click_users,
            COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_type = 'download') AS downloads,
            COUNT(DISTINCT COALESCE(e.app_user_id, e.user_id::text)) FILTER (WHERE e.event_type = 'app_register') AS registrations,
            COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_type = 'payment') AS payments,
            COALESCE(SUM(e.amount_cents) FILTER (WHERE e.event_type = 'payment'), 0) AS revenue_cents
        FROM attribution_events e
        LEFT JOIN attribution_links l ON l.tracking_id = e.tracking_id
        WHERE {event_window_alias}
        GROUP BY 1
        ORDER BY {{order_expr}} DESC, clicks DESC
        LIMIT 10
    """
    country_rows = await fetch_rows(
        f"""
        SELECT
            COALESCE(e.country_code, l.country_code, 'UNKNOWN') AS key,
            COUNT(*) FILTER (WHERE e.event_type = 'link_exposed') AS exposures,
            COUNT(*) FILTER (WHERE e.event_type = 'click') AS clicks,
            COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_type = 'click') AS click_users,
            COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_type = 'download') AS downloads,
            COUNT(DISTINCT COALESCE(e.app_user_id, e.user_id::text)) FILTER (WHERE e.event_type = 'app_register') AS registrations,
            COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_type = 'payment') AS payments,
            COALESCE(SUM(e.amount_cents) FILTER (WHERE e.event_type = 'payment'), 0) AS revenue_cents,
            BOOL_OR(COALESCE(l.is_t1_country, false)) AS is_t1_country
        FROM attribution_events e
        LEFT JOIN attribution_links l ON l.tracking_id = e.tracking_id
        WHERE {event_window_alias}
        GROUP BY 1
        ORDER BY clicks DESC, payments DESC
        LIMIT 10
        """
    )
    age_rows = await fetch_rows(
        dimension_sql.format(
            key_expr=(
                "CASE "
                "WHEN COALESCE(e.age, l.age) IS NULL THEN 'unknown' "
                "WHEN COALESCE(e.age, l.age) < 18 THEN '<18' "
                "WHEN COALESCE(e.age, l.age) BETWEEN 18 AND 24 THEN '18-24' "
                "WHEN COALESCE(e.age, l.age) BETWEEN 25 AND 34 THEN '25-34' "
                "WHEN COALESCE(e.age, l.age) BETWEEN 35 AND 44 THEN '35-44' "
                "ELSE '45+' END"
            ),
            order_expr="clicks",
        )
    )
    level_rows = await fetch_rows(
        dimension_sql.format(
            key_expr="COALESCE(e.user_level, l.user_level, 'UNKNOWN')",
            order_expr="payments",
        )
    )
    persona_rows = await fetch_rows(
        dimension_sql.format(key_expr="COALESCE(l.persona_slug, 'unknown')", order_expr="payments")
    )
    intent_rows = await fetch_rows(
        dimension_sql.format(key_expr="COALESCE(l.intent, 'unknown')", order_expr="payments")
    )
    platform_rows = await fetch_rows(
        dimension_sql.format(key_expr="COALESCE(l.platform, 'unknown')", order_expr="clicks")
    )
    device_rows = await fetch_rows(
        dimension_sql.format(key_expr="COALESCE(e.device_os, 'unknown')", order_expr="clicks")
    )
    account_rows = await fetch_rows(
        dimension_sql.format(key_expr="COALESCE(l.sender_account_id, 'unknown')", order_expr="clicks")
    )
    category_rows = await fetch_rows(
        dimension_sql.format(key_expr="COALESCE(l.script_category, 'unknown')", order_expr="payments")
    )

    script_sql = f"""
        SELECT
            COALESCE(l.script_hit_id, l.script_template_id::text, 'unknown') AS script_key,
            MIN(l.script_template_id::text) AS script_template_id,
            MIN(l.script_hit_id) AS script_hit_id,
            MIN(l.intent) AS intent,
            MIN(l.persona_slug) AS persona,
            MIN(l.scene_step) AS scene_step,
            MIN(l.sender_account_id) AS sender_account_id,
            COUNT(*) FILTER (WHERE e.event_type = 'click') AS clicks,
            COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_type = 'download') AS downloads,
            COUNT(DISTINCT COALESCE(e.app_user_id, e.user_id::text)) FILTER (WHERE e.event_type = 'app_register') AS registrations,
            COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_type = 'payment') AS payments,
            COALESCE(SUM(e.amount_cents) FILTER (WHERE e.event_type = 'payment'), 0) AS revenue_cents
        FROM attribution_events e
        LEFT JOIN attribution_links l ON l.tracking_id = e.tracking_id
        WHERE {event_window_alias}
        GROUP BY 1
        ORDER BY {{order_expr}} DESC, clicks DESC
        LIMIT 10
    """
    top_click_scripts = await fetch_rows(script_sql.format(order_expr="clicks"))
    top_download_scripts = await fetch_rows(script_sql.format(order_expr="downloads"))
    top_register_scripts = await fetch_rows(script_sql.format(order_expr="registrations"))
    top_payment_scripts = await fetch_rows(script_sql.format(order_expr="payments"))
    link_rows = await fetch_rows(
        f"""
        SELECT
            l.tracking_id,
            l.destination_url,
            COALESCE(l.script_hit_id, l.script_template_id::text, 'unknown') AS script_key,
            l.sent_at,
            l.sender_account_id,
            l.platform,
            COUNT(*) FILTER (WHERE e.event_type = 'click') AS clicks,
            COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_type = 'click') AS click_users,
            MIN(e.created_at) FILTER (WHERE e.event_type = 'click') AS first_click_at,
            COALESCE(AVG(EXTRACT(EPOCH FROM (e.created_at - COALESCE(l.sent_at, l.created_at)))) FILTER (
                WHERE e.event_type = 'click'
            ), 0) AS avg_seconds_to_click
        FROM attribution_links l
        LEFT JOIN attribution_events e ON e.tracking_id = l.tracking_id
        WHERE {link_window}
        GROUP BY l.tracking_id, l.destination_url, script_key, l.sent_at, l.sender_account_id, l.platform
        ORDER BY clicks DESC, click_users DESC
        LIMIT 20
        """
    )
    telegram_account_rows = await fetch_rows(
        f"""
        SELECT
            ta.id::text AS account_id,
            COALESCE(NULLIF(ta.display_name, ''), NULLIF(ta.username, ''), ta.phone, ta.id::text) AS account_label,
            ta.phone,
            ta.username,
            COUNT(DISTINCT c.user_id) FILTER (WHERE m.id IS NOT NULL) AS served_users,
            COUNT(DISTINCT c.user_id) FILTER (
                WHERE m.id IS NOT NULL
                  AND {user_window}
            ) AS new_users,
            COUNT(m.id) AS assistant_messages,
            MAX(m.created_at) AS last_message_at
        FROM telegram_accounts ta
        LEFT JOIN messages m
          ON m.sender_id = ta.id::text
         AND m.sender_type = 'assistant'
         AND {event_window.replace("created_at", "m.created_at")}
        LEFT JOIN conversations c ON c.id = m.conversation_id
        LEFT JOIN users u ON u.id = c.user_id AND u.channel = 'telegram_real_user'
        GROUP BY ta.id, ta.display_name, ta.username, ta.phone
        ORDER BY served_users DESC, new_users DESC, assistant_messages DESC, account_label ASC
        LIMIT 50
        """
    )

    def value(row: Any, idx: int, default: Any = 0) -> Any:
        try:
            return row[idx]
        except Exception:
            return default

    def rate(numerator: int, denominator: int) -> float:
        return numerator / denominator if denominator else 0

    def dimension(row: Any) -> dict[str, Any]:
        return {
            "key": value(row, 0, "unknown"),
            "exposures": int(value(row, 1) or 0),
            "clicks": int(value(row, 2) or 0),
            "click_users": int(value(row, 3) or 0),
            "downloads": int(value(row, 4) or 0),
            "registrations": int(value(row, 5) or 0),
            "payments": int(value(row, 6) or 0),
            "revenue_cents": int(value(row, 7) or 0),
        }

    def script(row: Any) -> dict[str, Any]:
        return {
            "script_key": value(row, 0, "unknown"),
            "script_template_id": value(row, 1, None),
            "script_hit_id": value(row, 2, None),
            "intent": value(row, 3, None),
            "persona": value(row, 4, None),
            "scene_step": value(row, 5, None),
            "sender_account_id": value(row, 6, None),
            "clicks": int(value(row, 7) or 0),
            "downloads": int(value(row, 8) or 0),
            "registrations": int(value(row, 9) or 0),
            "payments": int(value(row, 10) or 0),
            "revenue_cents": int(value(row, 11) or 0),
        }

    sent_links = int(value(overview, 0) or 0)
    sent_users = int(value(overview, 1) or 0)
    exposed_links = int(value(overview, 2) or 0)
    exposed_users = int(value(overview, 3) or 0)
    clicked_links = int(value(overview, 4) or 0)
    click_users = int(value(overview, 5) or 0)
    click_events = int(value(overview, 6) or 0)
    download_page_users = int(value(overview, 7) or 0)
    downloads = int(value(overview, 8) or 0)
    registrations = int(value(overview, 9) or 0)
    payments = int(value(overview, 10) or 0)
    revenue_cents = int(value(overview, 11) or 0)
    upgraded_paid_users = int(value(overview, 12) or 0)
    today_click_users = int(value(overview, 13) or 0)
    tg_new_users = sum(int(value(r, 5) or 0) for r in telegram_account_rows)
    tg_served_users = sum(int(value(r, 4) or 0) for r in telegram_account_rows)
    return {
        "days": days,
        "date": selected_date.isoformat() if selected_date else None,
        "mode": "daily" if selected_date else "range",
        "overview": {
            "sent_links": sent_links,
            "sent_users": sent_users,
            "exposed_links": exposed_links,
            "exposed_users": exposed_users,
            "clicked_links": clicked_links,
            "click_events": click_events,
            "click_users": click_users,
            "unique_click_users": click_users,
            "today_click_users": today_click_users,
            "download_page_users": download_page_users,
            "download_users": downloads,
            "register_users": registrations,
            "paid_users": payments,
            "upgraded_paid_users": upgraded_paid_users,
            "revenue_cents": revenue_cents,
            "click_rate": rate(click_users, sent_users or exposed_users),
            "click_to_download_page_rate": rate(download_page_users, click_users),
            "click_to_download_rate": rate(downloads, click_users),
            "download_to_register_rate": rate(registrations, downloads),
            "click_to_register_rate": rate(registrations, click_users),
            "register_to_pay_rate": rate(payments, registrations),
            "click_to_pay_rate": rate(payments, click_users),
            "avg_sent_to_click_seconds": float(value(overview, 14) or 0),
            "avg_click_to_register_seconds": float(value(overview, 15) or 0),
            "avg_click_to_payment_seconds": float(value(overview, 16) or 0),
            "tg_new_users": tg_new_users,
            "tg_served_users": tg_served_users,
        },
        "funnel": [
            {"step": "话术发送", "users": sent_users, "events": sent_links},
            {"step": "链接曝光", "users": exposed_users, "events": exposed_links},
            {"step": "链接点击", "users": click_users, "events": click_events},
            {"step": "下载页访问", "users": download_page_users, "events": download_page_users},
            {"step": "App 下载", "users": downloads, "events": downloads},
            {"step": "App 注册", "users": registrations, "events": registrations},
            {"step": "首次付费", "users": payments, "events": payments},
            {"step": "累计付费升 A/S", "users": upgraded_paid_users, "events": upgraded_paid_users},
        ],
        "countries": [
            {
                **dimension(r),
                "country_code": value(r, 0, "UNKNOWN"),
                "is_t1_country": bool(value(r, 8, False)),
            }
            for r in country_rows
        ],
        "age_bands": [dimension(r) for r in age_rows],
        "levels": [dimension(r) for r in level_rows],
        "personas": [dimension(r) for r in persona_rows],
        "intents": [dimension(r) for r in intent_rows],
        "platforms": [dimension(r) for r in platform_rows],
        "devices": [dimension(r) for r in device_rows],
        "sender_accounts": [dimension(r) for r in account_rows],
        "script_categories": [dimension(r) for r in category_rows],
        "top_click_scripts": [script(r) for r in top_click_scripts],
        "top_download_scripts": [script(r) for r in top_download_scripts],
        "top_register_scripts": [script(r) for r in top_register_scripts],
        "top_payment_scripts": [script(r) for r in top_payment_scripts],
        "top_scripts": [script(r) for r in top_payment_scripts],
        "links": [
            {
                "tracking_id": value(r, 0, ""),
                "destination_url": value(r, 1, ""),
                "script_key": value(r, 2, "unknown"),
                "sent_at": value(r, 3, None).isoformat() if value(r, 3, None) else None,
                "sender_account_id": value(r, 4, None),
                "platform": value(r, 5, None),
                "clicks": int(value(r, 6) or 0),
                "click_users": int(value(r, 7) or 0),
                "first_click_at": value(r, 8, None).isoformat() if value(r, 8, None) else None,
                "avg_seconds_to_click": float(value(r, 9) or 0),
            }
            for r in link_rows
        ],
        "telegram_accounts": [
            {
                "account_id": value(r, 0, ""),
                "account_label": value(r, 1, "unknown"),
                "phone": value(r, 2, None),
                "username": value(r, 3, None),
                "served_users": int(value(r, 4) or 0),
                "new_users": int(value(r, 5) or 0),
                "assistant_messages": int(value(r, 6) or 0),
                "last_message_at": value(r, 7, None).isoformat() if value(r, 7, None) else None,
            }
            for r in telegram_account_rows
        ],
    }
