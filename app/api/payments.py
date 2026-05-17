"""
D6-1: Stripe Checkout

POST /api/v1/orders   — 创建订单 + Stripe Checkout Session，返回 checkout_url
GET  /api/v1/orders/{order_id} — 从 DB 读取订单状态

不在此处实现：
- Webhook 验签 / 幂等（D6-2，由 Cursor 负责）
- 单元测试（Cursor 负责）
"""

from fastapi import APIRouter, BackgroundTasks, Request, HTTPException, Depends, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from core.database import AsyncSessionLocal, get_db
from core.config import settings
from loguru import logger
from services.stripe_webhook import (
    SignatureError,
    claim_event,
    handle_event,
    verify_and_parse_event,
)
from services.minor_protection import (
    AGE_VERIFICATION_REQUIRED_DETAIL,
    MINOR_BLOCK_DETAIL,
    should_block_consumption,
)
import json
import stripe
import uuid
import time

router = APIRouter()


# ── 请求 / 响应模型 ────────────────────────────────────

class OrderCreate(BaseModel):
    user_id: str
    product_id: str
    amount: int          # 单位：分（cents）
    currency: str = "USD"


class OrderResponse(BaseModel):
    order_id: str
    checkout_url: str
    status: str


# ── POST /api/v1/orders ───────────────────────────────

@router.post("/orders", response_model=OrderResponse)
async def create_order(
    data: OrderCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))
    start_ts = time.time()

    log = logger.bind(
        trace_id=trace_id,
        component="payments",
        user_id=data.user_id,
        product_id=data.product_id,
        amount=data.amount,
        currency=data.currency,
    )
    log.info("payments.order.create.start")

    user_row = (
        await db.execute(
            text(
                """
                SELECT id, status, age_verified, is_minor_suspected
                FROM users
                WHERE id = :uid
                """
            ),
            {"uid": data.user_id},
        )
    ).fetchone()
    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")
    if str(user_row[1] or "active") != "active":
        raise HTTPException(status_code=409, detail="User is not active")
    block_reason = should_block_consumption(
        age_verified=bool(user_row[2]),
        is_minor_suspected=bool(user_row[3]),
    )
    if block_reason == "minor_suspected":
        log.bind(block_reason=block_reason).warning("payments.order.minor_blocked")
        raise HTTPException(status_code=403, detail=MINOR_BLOCK_DETAIL)
    if block_reason == "age_not_verified":
        log.bind(block_reason=block_reason).warning("payments.order.age_verification_required")
        raise HTTPException(status_code=403, detail=AGE_VERIFICATION_REQUIRED_DETAIL)

    # ── 1. 写入 orders 表（status=pending）──────────────
    order_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO orders "
            "(id, user_id, product_id, amount, currency, status, payment_provider) "
            "VALUES (:id, :user_id, :product_id, :amount, :currency, 'pending', 'stripe')"
        ),
        {
            "id": order_id,
            "user_id": data.user_id,
            "product_id": data.product_id,
            "amount": data.amount,
            "currency": data.currency,
        },
    )
    await db.commit()
    log.bind(order_id=order_id).info("payments.order.db.inserted")

    # ── 2. 创建 Stripe Checkout Session ─────────────────
    stripe_key = settings.STRIPE_SECRET_KEY
    if not stripe_key:
        log.bind(result="failed", reason="STRIPE_SECRET_KEY not set").error(
            "payments.stripe.config_missing"
        )
        raise HTTPException(status_code=503, detail="Stripe not configured")

    stripe.api_key = stripe_key

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": data.currency.lower(),
                        "unit_amount": data.amount,
                        "product_data": {"name": data.product_id},
                    },
                    "quantity": 1,
                }
            ],
            metadata={
                "order_id": order_id,
                "user_id": data.user_id,
            },
            success_url=settings.STRIPE_SUCCESS_URL,
            cancel_url=settings.STRIPE_CANCEL_URL,
        )
    except stripe.StripeError as exc:
        log.bind(
            order_id=order_id,
            result="failed",
            error_type=type(exc).__name__,
        ).error("payments.stripe.session.failed")
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc.user_message or str(exc)}")

    checkout_url = session.url
    session_id = session.id
    log.bind(order_id=order_id, session_id=session_id).info("payments.stripe.session.created")

    # ── 3. 更新 orders.provider_order_id ────────────────
    await db.execute(
        text(
            "UPDATE orders SET provider_order_id = :sid WHERE id = :oid"
        ),
        {"sid": session_id, "oid": order_id},
    )
    await db.commit()
    log.bind(order_id=order_id, session_id=session_id).info("payments.order.db.updated")

    duration_ms = round((time.time() - start_ts) * 1000, 1)
    log.bind(
        order_id=order_id,
        result="success",
        duration_ms=duration_ms,
    ).info("payments.order.create.done")

    return OrderResponse(
        order_id=order_id,
        checkout_url=checkout_url,
        status="pending",
    )


# ── GET /api/v1/orders/{order_id} ────────────────────

@router.get("/orders/{order_id}")
async def get_order(
    order_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))
    log = logger.bind(trace_id=trace_id, component="payments", order_id=order_id)
    log.info("payments.order.get.start")

    row = (
        await db.execute(
            text(
                "SELECT id, user_id, product_id, amount, currency, status, "
                "payment_provider, provider_order_id, created_at "
                "FROM orders WHERE id = :oid"
            ),
            {"oid": order_id},
        )
    ).fetchone()

    if not row:
        log.bind(result="not_found").warning("payments.order.get.not_found")
        raise HTTPException(status_code=404, detail="Order not found")

    log.bind(result="success", status=row[5]).info("payments.order.get.done")

    return {
        "order_id":          str(row[0]),
        "user_id":           str(row[1]),
        "product_id":        row[2],
        "amount":            row[3],
        "currency":          row[4],
        "status":            row[5],
        "payment_provider":  row[6],
        "provider_order_id": row[7],
        "created_at":        row[8].isoformat() if row[8] else None,
    }


# ── POST /api/v1/webhooks/stripe ─────────────────────
# D6-2: 验签 + stripe_webhook_events 幂等 + 5 秒内 ack（异步处理业务）
#
# 设计要点：
# - 入口同步只做三件事：验签 / 幂等抢占 / 触发后台处理 → 几十毫秒内返回 200。
# - 真正的业务（订单 paid / vip_level 累加）在 BackgroundTasks 里跑，处理完
#   把 result 写回 stripe_webhook_events。Stripe 重发同一 event_id 时会被
#   ``stripe_webhook_events.event_id`` 的 PK ON CONFLICT 直接挡掉。
# - 验签失败 → 400，连 DB 都不查（防止被随便 POST 撑爆 events 表）。

async def _process_event_in_background(event: dict) -> None:
    """后台任务：在新 Session 里处理已抢占的 event。"""
    async with AsyncSessionLocal() as session:
        try:
            await handle_event(session, event)
        finally:
            await session.close()


@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))
    log = logger.bind(trace_id=trace_id, component="stripe_webhook")
    log.info("stripe_webhook.received")

    body = await request.body()
    signature = request.headers.get("stripe-signature", "")

    # 1. 验签（同步）
    try:
        event = verify_and_parse_event(body, signature)
    except SignatureError as exc:
        log.bind(result="signature_failed", reason=str(exc)).warning(
            "stripe_webhook.verify_failed"
        )
        response.status_code = 400
        return {"status": "signature_failed"}

    event_id = event.get("id") or ""
    event_type = event.get("type") or ""
    log = log.bind(event_id=event_id, event_type=event_type)

    if not event_id:
        log.warning("stripe_webhook.missing_event_id")
        response.status_code = 400
        return {"status": "missing_event_id"}

    # 2. 抢占（DB 唯一约束保证幂等）
    is_new = await claim_event(
        db,
        event_id=event_id,
        event_type=event_type,
        payload_json=json.dumps(event, default=str, ensure_ascii=False),
    )
    if not is_new:
        log.bind(result="duplicate").info("stripe_webhook.duplicate")
        return {"status": "duplicate", "event_id": event_id}

    # 3. 5 秒内 ack；真正业务异步处理
    background_tasks.add_task(_process_event_in_background, event)
    log.info("stripe_webhook.queued")
    return {"status": "queued", "event_id": event_id}
