"""Stripe webhook service.

The API layer verifies signatures, claims the event id, and dispatches here.
This module keeps webhook handling idempotent and side-effect failures local so
Stripe retries do not amplify transient business errors.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import stripe
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from services.level_engine import UserLevelInput, calc_user_level
from services.minor_protection import should_block_consumption

try:
    from api.realtime import notify_user_upgrade
except ImportError:
    async def notify_user_upgrade(*args, **kwargs):
        pass


class SignatureError(Exception):
    """Stripe signature validation failed or webhook secret is missing."""


def verify_and_parse_event(body: bytes, signature: str) -> dict[str, Any]:
    """Verify Stripe signature and return an event dict."""
    secret = settings.STRIPE_WEBHOOK_SECRET
    if not secret:
        raise SignatureError("STRIPE_WEBHOOK_SECRET not configured")
    try:
        event = stripe.Webhook.construct_event(body, signature, secret)
    except stripe.SignatureVerificationError as exc:
        raise SignatureError(f"invalid signature: {exc}") from exc
    except Exception as exc:
        raise SignatureError(f"event parse failed: {exc}") from exc
    return event


async def claim_event(
    db: AsyncSession,
    *,
    event_id: str,
    event_type: str,
    payload_json: str,
) -> bool:
    """Claim an event id once using INSERT ... ON CONFLICT DO NOTHING."""
    res = await db.execute(
        text(
            """
            INSERT INTO stripe_webhook_events (event_id, event_type, payload, result)
            VALUES (:event_id, :event_type, CAST(:payload AS jsonb), 'received')
            ON CONFLICT (event_id) DO NOTHING
            RETURNING event_id
            """
        ),
        {"event_id": event_id, "event_type": event_type, "payload": payload_json},
    )
    row = res.fetchone()
    await db.commit()
    return row is not None


async def _mark_result(
    db: AsyncSession,
    *,
    event_id: str,
    result: str,
    error: Optional[str] = None,
) -> None:
    """Persist final webhook processing state without re-raising failures."""
    try:
        await db.execute(
            text(
                """
                UPDATE stripe_webhook_events
                SET result = :result, error = :error, handled_at = :handled_at
                WHERE event_id = :event_id
                """
            ),
            {
                "result": result,
                "error": error,
                "handled_at": datetime.now(timezone.utc).replace(tzinfo=None),
                "event_id": event_id,
            },
        )
        await db.commit()
    except Exception:
        logger.bind(component="stripe_webhook", event_id=event_id).exception(
            "stripe_webhook.mark_result_failed"
        )


async def handle_event(db: AsyncSession, event: dict[str, Any]) -> str:
    """Dispatch supported Stripe events and record a final result."""
    event_id = event.get("id", "")
    event_type = event.get("type", "")
    log = logger.bind(
        component="stripe_webhook", event_id=event_id, event_type=event_type
    )
    try:
        if event_type == "checkout.session.completed":
            await _handle_checkout_completed(db, event)
            await _mark_result(db, event_id=event_id, result="processed")
            log.info("stripe_webhook.processed")
            return "processed"
        await _mark_result(db, event_id=event_id, result="ignored")
        log.info("stripe_webhook.ignored")
        return "ignored"
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).exception("stripe_webhook.failed")
        await _mark_result(db, event_id=event_id, result="failed", error=str(exc))
        return "failed"


async def _handle_checkout_completed(db: AsyncSession, event: dict[str, Any]) -> None:
    """Mark an order paid, increment VIP, and recalculate level/chat route."""
    session = event.get("data", {}).get("object", {}) or {}
    metadata = session.get("metadata") or {}
    order_id = metadata.get("order_id")
    if not order_id:
        session_id = session.get("id")
        if not session_id:
            raise ValueError("missing order_id and session.id")
        row = (
            await db.execute(
                text("SELECT id FROM orders WHERE provider_order_id = :sid"),
                {"sid": session_id},
            )
        ).fetchone()
        if not row:
            raise ValueError(f"order not found for session_id={session_id}")
        order_id = str(row[0])

    res = await db.execute(
        text(
            """
            UPDATE orders
            SET status = 'paid', paid_at = NOW()
            WHERE id = :oid AND status <> 'paid'
            RETURNING user_id
            """
        ),
        {"oid": order_id},
    )
    paid_row = res.fetchone()
    if paid_row is None:
        exists = (
            await db.execute(
                text("SELECT 1 FROM orders WHERE id = :oid"),
                {"oid": order_id},
            )
        ).fetchone()
        if exists is None:
            raise ValueError(f"order not found: {order_id}")
        await db.commit()
        return

    user_id = paid_row[0]
    if user_id is None:
        await db.commit()
        return

    user_row = (
        await db.execute(
            text(
                """
                SELECT age_verified, is_minor_suspected
                FROM users
                WHERE id = :uid
                """
            ),
            {"uid": user_id},
        )
    ).fetchone()
    if user_row is not None:
        block_reason = should_block_consumption(
            age_verified=bool(user_row[0]),
            is_minor_suspected=bool(user_row[1]),
        )
        if block_reason:
            await db.execute(
                text(
                    """
                    UPDATE orders
                    SET status = 'blocked_minor',
                        refund_status = 'review_required'
                    WHERE id = :oid
                    """
                ),
                {"oid": order_id},
            )
            await db.commit()
            logger.bind(
                component="stripe_webhook",
                order_id=order_id,
                user_id=str(user_id),
                block_reason=block_reason,
            ).warning("stripe_webhook.minor_protection.vip_blocked")
            return

    await db.execute(
        text(
            """
            INSERT INTO user_profiles (user_id, vip_level)
            VALUES (:uid, 1)
            ON CONFLICT (user_id) DO UPDATE
            SET vip_level = COALESCE(user_profiles.vip_level, 0) + 1,
                updated_at = NOW()
            """
        ),
        {"uid": user_id},
    )

    try:
        await _recalculate_paid_user_level(db, user_id=user_id)
    except Exception as upgrade_exc:
        logger.bind(
            component="stripe_webhook",
            user_id=str(user_id),
            error_type=type(upgrade_exc).__name__,
        ).warning("stripe_webhook.user_level_recalc_failed")

    await db.commit()


async def _recalculate_paid_user_level(db: AsyncSession, *, user_id: Any) -> None:
    spend_row = (
        await db.execute(
            text(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM orders
                WHERE user_id = :uid
                  AND status = 'paid'
                  AND UPPER(COALESCE(currency, 'USD')) = 'USD'
                """
            ),
            {"uid": user_id},
        )
    ).fetchone()
    lifetime_spend_usd = float(_row_value(spend_row, 0, 0) or 0) / 100.0

    profile_row = (
        await db.execute(
            text(
                """
                SELECT
                    COALESCE(vip_level, 0) AS vip_level,
                    COALESCE(preferences, '{}'::jsonb) AS preferences,
                    COALESCE(user_level, 'C') AS user_level,
                    country_code
                FROM user_profiles
                WHERE user_id = :uid
                """
            ),
            {"uid": user_id},
        )
    ).fetchone()
    if profile_row is None:
        return

    vip_level = int(_row_value(profile_row, 0, 0) or 0)
    preferences = _row_value(profile_row, 1, {}) or {}
    previous_level = str(_row_value(profile_row, 2, "C") or "C").upper()
    country_code = _row_value(profile_row, 3, None) or _country_from_preferences(preferences)

    result = calc_user_level(
        UserLevelInput(
            profile_complete=True,
            country_code=country_code,
            lifetime_spend_usd=lifetime_spend_usd,
            vip_level=vip_level,
        )
    )

    await db.execute(
        text(
            """
            UPDATE user_profiles
            SET user_level = :user_level,
                chat_route = :chat_route,
                level_updated_at = NOW(),
                level_reason = jsonb_build_object(
                    'source', 'payment_completed',
                    'previous_level', :previous_level,
                    'country_tier', :country_tier,
                    'lifetime_spend_usd', :lifetime_spend_usd,
                    'reason', :reason
                ),
                updated_at = NOW()
            WHERE user_id = :uid
            """
        ),
        {
            "uid": user_id,
            "user_level": result.level,
            "chat_route": result.chat_route,
            "previous_level": previous_level,
            "country_tier": result.country_tier,
            "lifetime_spend_usd": lifetime_spend_usd,
            "reason": result.reason,
        },
    )

    if previous_level != result.level:
        await notify_user_upgrade(
            user_id=str(user_id),
            previous_level=previous_level,
            new_level=result.level,
            reason="payment_completed",
        )
        logger.bind(
            component="stripe_webhook",
            user_id=str(user_id),
            previous_level=previous_level,
            new_level=result.level,
            chat_route=result.chat_route,
        ).info("stripe_webhook.user_level_recalculated")


def _country_from_preferences(preferences: Any) -> str | None:
    if isinstance(preferences, dict):
        value = preferences.get("country_code")
        return str(value).upper() if value else None
    return None


def _row_value(row: Any, index: int, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        return row[index]
    except (IndexError, KeyError, TypeError):
        return default
