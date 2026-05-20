"""
D6-2 Stripe Webhook 服务层

- ``verify_and_parse_event``：用 ``settings.STRIPE_WEBHOOK_SECRET`` 验签并解析 event。
  签名错或缺 secret 抛 ``SignatureError``（路由层捕获返回 400）。
- ``claim_event``：往 ``stripe_webhook_events`` 表插一行（ON CONFLICT DO NOTHING）。
  返回 ``True`` = 本次首次到达；``False`` = 重复事件，调用方应直接 200 收尾。
- ``handle_event``：根据 ``event_type`` 调对应处理器；当前只处理
  ``checkout.session.completed``。处理结果会回写到同一行的 ``result/handled_at/error``。

把"验签/幂等/分发"全部从路由抽出来，路由就只剩薄薄一层胶水，便于单测。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import stripe
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from services.minor_protection import should_block_consumption


# 导入 WebSocket 通知函数 (P2-11)
try:
    from api.realtime import notify_user_upgrade
except ImportError:
    # 如果导入失败（循环依赖），提供一个空实现
    async def notify_user_upgrade(*args, **kwargs):
        pass


class SignatureError(Exception):
    """验签失败或缺少 STRIPE_WEBHOOK_SECRET。"""


def verify_and_parse_event(body: bytes, signature: str) -> dict[str, Any]:
    """同步函数：验签并返回 event dict。失败抛 ``SignatureError``。"""
    secret = settings.STRIPE_WEBHOOK_SECRET
    if not secret:
        # 缺 secret 拒绝处理，避免在生产里"假装通过"
        raise SignatureError("STRIPE_WEBHOOK_SECRET not configured")
    try:
        event = stripe.Webhook.construct_event(body, signature, secret)
    except stripe.SignatureVerificationError as exc:
        raise SignatureError(f"invalid signature: {exc}") from exc
    except Exception as exc:  # 包括 ValueError(payload 不合法)
        raise SignatureError(f"event parse failed: {exc}") from exc
    return event


async def claim_event(
    db: AsyncSession,
    *,
    event_id: str,
    event_type: str,
    payload_json: str,
) -> bool:
    """尝试占用 event_id。返回 True=本次首次写入；False=已存在（重复事件）。

    用 ``INSERT ... ON CONFLICT DO NOTHING RETURNING event_id`` 一条 SQL 完成抢占。
    """
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
    """处理完更新 result/handled_at/error。任何异常都吞掉只记日志，避免反向影响 webhook。"""
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
    """根据 event_type 调用对应处理器。返回最终 result 字符串。

    捕获处理器异常并写 result='failed'。
    """
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
        # 其它事件先 ack 不出错，便于将来按需扩展
        await _mark_result(db, event_id=event_id, result="ignored")
        log.info("stripe_webhook.ignored")
        return "ignored"
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).exception("stripe_webhook.failed")
        await _mark_result(db, event_id=event_id, result="failed", error=str(exc))
        return "failed"


async def _handle_checkout_completed(db: AsyncSession, event: dict[str, Any]) -> None:
    """checkout.session.completed → orders.status='paid' + users.vip_level += 1。

    通过 ``metadata.order_id``（D6-1 创建 session 时写入）定位订单，避免依赖
    Stripe 的 session.id ↔ orders.provider_order_id 索引（虽然两者都有）。
    """
    session = event.get("data", {}).get("object", {}) or {}
    metadata = session.get("metadata") or {}
    order_id = metadata.get("order_id")
    if not order_id:
        # 兜底用 provider_order_id 反查
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

    # 1. orders → paid
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
        # 订单不存在 → 抛；订单已 paid → 视为成功（幂等）。
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

    # 2. users.vip_level += 1（最简策略；后续 D6 可按 product_id 计算等级）
    if user_id is not None:
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
                "UPDATE users SET vip_level = COALESCE(vip_level, 0) + 1 WHERE id = :uid"
            ),
            {"uid": user_id},
        )
        
        # P2-11: 触发用户升级 WebSocket 通知（简化版本，后续 P2 分级引擎会完善）
        # 当前假设付费成功后升级到 A 级，实际分级逻辑由 P2 分级引擎处理
        try:
            # 获取当前用户等级
            profile_row = await db.execute(
                text(
                    """
                    SELECT user_level FROM user_profiles 
                    WHERE user_id = :uid
                    """
                ),
                {"uid": user_id},
            )
            current_level = profile_row.scalar()
            
            if current_level and current_level != "S":
                # 如果当前不是 S 级，升级到 A 级（简化逻辑）
                new_level = "A"
                await db.execute(
                    text(
                        """
                        UPDATE user_profiles 
                        SET user_level = :new_level, 
                            level_updated_at = NOW(),
                            level_reason = jsonb_build_object('source', 'payment_completed', 'previous_level', :current_level)
                        WHERE user_id = :uid
                        """
                    ),
                    {"uid": user_id, "new_level": new_level, "current_level": current_level},
                )
                await db.commit()
                
                # 触发 WebSocket 通知
                await notify_user_upgrade(
                    user_id=str(user_id),
                    previous_level=current_level,
                    new_level=new_level,
                    reason="payment_completed",
                )
                
                logger.bind(
                    component="stripe_webhook",
                    user_id=str(user_id),
                    previous_level=current_level,
                    new_level=new_level,
                ).info("stripe_webhook.user_upgrade_notified")
        except Exception as upgrade_exc:
            # 升级通知失败不影响主流程
            logger.bind(
                component="stripe_webhook",
                user_id=str(user_id),
                error_type=type(upgrade_exc).__name__,
            ).warning("stripe_webhook.user_upgrade_failed")
    
    await db.commit()
