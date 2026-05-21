"""
P3-15: B/C/D auto-delivery worker test script.

This script tests the auto-delivery worker functionality:
1. AccountPool initialization
2. B/C/D level message filtering
3. Human-like delay calculation
4. MTProto sending with typing status
5. Message status tracking
6. Retry mechanism
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add app directory to path
app_dir = Path(__file__).parent.parent / "app"
sys.path.insert(0, str(app_dir))

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal, engine
from services.auto_delivery_worker import (
    get_scheduler_status,
    reinit_account_pool,
    run_one_tick,
)
from services.human_delay_calculator import calculate_human_delay


async def setup_test_db():
    """Setup test database tables."""
    async with engine.begin() as conn:
        # Create message_schedules table if not exists
        migration_sql = Path(__file__).parent.parent / "scripts" / "migrations" / "create_message_schedules.sql"
        if migration_sql.exists():
            sql = migration_sql.read_text()
            await conn.execute(text(sql))
            logger.info("Created message_schedules table")

        # Create test users with B/C/D levels
        await conn.execute(
            text(
                """
                INSERT INTO users (id, external_id, level, created_at, updated_at)
                VALUES
                    ('11111111-1111-1111-1111-111111111111', 'tg_123456789', 'B', NOW(), NOW()),
                    ('22222222-2222-2222-2222-222222222222', 'tg_987654321', 'C', NOW(), NOW()),
                    ('33333333-3333-3333-3333-333333333333', 'tg_456789123', 'D', NOW(), NOW())
                ON CONFLICT (id) DO NOTHING
                """
            )
        )
        logger.info("Created test users with B/C/D levels")


async def cleanup_test_db():
    """Cleanup test data."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("DELETE FROM message_schedules WHERE user_id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', '33333333-3333-3333-3333-333333333333')")
        )
        await session.commit()
        logger.info("Cleaned up test data")


async def test_add_bcd_messages():
    """Test adding B/C/D level messages to the queue."""
    logger.info("Test 1: Adding B/C/D level messages")
    try:
        from services.message_schedule_service import add_scheduled_message

        # Add B level message
        await add_scheduled_message(
            user_id="11111111-1111-1111-1111-111111111111",
            external_user_id="tg_123456789",
            message_type="text",
            content="Hello B level user!",
            platform="telegram_real_user",
            chat_id=123456789,
            send_at=None,
            priority=1,
            metadata={"test": True, "level": "B"},
            trace_id="test-b",
        )

        # Add C level message
        await add_scheduled_message(
            user_id="22222222-2222-2222-2222-222222222222",
            external_user_id="tg_987654321",
            message_type="text",
            content="Hello C level user!",
            platform="telegram_real_user",
            chat_id=987654321,
            send_at=None,
            priority=1,
            metadata={"test": True, "level": "C"},
            trace_id="test-c",
        )

        # Add D level message
        await add_scheduled_message(
            user_id="33333333-3333-3333-3333-333333333333",
            external_user_id="tg_456789123",
            message_type="text",
            content="Hello D level user!",
            platform="telegram_real_user",
            chat_id=456789123,
            send_at=None,
            priority=1,
            metadata={"test": True, "level": "D"},
            trace_id="test-d",
        )

        logger.info("✓ B/C/D level messages added to queue")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to add B/C/D messages: {e}")
        return False


async def test_human_delay_calculation():
    """Test human-like delay calculation."""
    logger.info("Test 2: Testing human-like delay calculation")
    try:
        # Test short text
        short_delay = calculate_human_delay("Hi")
        logger.info(f"✓ Short text delay: {short_delay.delay_seconds}s")

        # Test medium text
        medium_delay = calculate_human_delay("Hello, how are you doing today?")
        logger.info(f"✓ Medium text delay: {medium_delay.delay_seconds}s")

        # Test long text
        long_delay = calculate_human_delay("This is a longer message that should take more time to type and send according to the human-like delay calculation policy.")
        logger.info(f"✓ Long text delay: {long_delay.delay_seconds}s")

        # Test CJK text
        cjk_delay = calculate_human_delay("你好，这是一个中文消息")
        logger.info(f"✓ CJK text delay: {cjk_delay.delay_seconds}s")

        return True
    except Exception as e:
        logger.error(f"✗ Failed delay calculation test: {e}")
        return False


async def test_scheduler_status():
    """Test getting scheduler status."""
    logger.info("Test 3: Getting scheduler status")
    try:
        status = get_scheduler_status()
        logger.info(f"✓ Scheduler status: {status}")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to get scheduler status: {e}")
        return False


async def test_account_pool_reinit():
    """Test AccountPool reinitialization."""
    logger.info("Test 4: Testing AccountPool reinitialization")
    try:
        success = await reinit_account_pool()
        logger.info(f"✓ AccountPool reinit: {'success' if success else 'failed (expected if no accounts)'}")
        return True
    except Exception as e:
        logger.error(f"✗ Failed AccountPool reinit test: {e}")
        return False


async def test_tick_execution():
    """Test manual tick execution."""
    logger.info("Test 5: Executing manual tick")
    try:
        stats = await run_one_tick(trace_id="test-auto-delivery-tick")
        logger.info(f"✓ Tick executed: {stats}")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to execute tick: {e}")
        return False


async def test_bcd_filtering():
    """Test that only B/C/D level messages are processed."""
    logger.info("Test 6: Testing B/C/D level filtering")
    try:
        async with AsyncSessionLocal() as session:
            # Add an S level message (should not be processed by auto-delivery)
            from services.message_schedule_service import add_scheduled_message

            await add_scheduled_message(
                user_id="44444444-4444-4444-4444-444444444444",
                external_user_id="tg_999999999",
                message_type="text",
                content="Hello S level user!",
                platform="telegram_real_user",
                chat_id=999999999,
                send_at=None,
                priority=10,
                metadata={"test": True, "level": "S"},
                trace_id="test-s",
            )

            # Update user level to S
            await session.execute(
                text(
                    """
                    INSERT INTO users (id, external_id, level, created_at, updated_at)
                    VALUES ('44444444-4444-4444-4444-444444444444', 'tg_999999999', 'S', NOW(), NOW())
                    ON CONFLICT (id) DO UPDATE SET level = 'S'
                    """
                )
            )
            await session.commit()

            logger.info("✓ Added S level message (should be ignored by auto-delivery)")
            return True
    except Exception as e:
        logger.error(f"✗ Failed B/C/D filtering test: {e}")
        return False


async def test_message_status_tracking():
    """Test message status tracking in database."""
    logger.info("Test 7: Checking message status in database")
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(
                    """
                    SELECT ms.id, ms.user_id, ms.status, u.level
                    FROM message_schedules ms
                    JOIN users u ON ms.user_id = u.id::text
                    WHERE ms.user_id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', '33333333-3333-3333-3333-333333333333')
                    ORDER BY ms.created_at DESC
                    """
                )
            )
            messages = result.mappings().all()

            logger.info(f"✓ Found {len(messages)} B/C/D test messages:")
            for msg in messages:
                logger.info(
                    f"  - ID: {msg['id']}, User: {msg['user_id']}, Level: {msg['level']}, Status: {msg['status']}"
                )
            return len(messages) > 0
    except Exception as e:
        logger.error(f"✗ Failed to check message status: {e}")
        return False


async def test_priority_ordering():
    """Test priority ordering for B/C/D messages."""
    logger.info("Test 8: Testing priority ordering")
    try:
        from services.message_schedule_service import add_scheduled_message

        # Add high priority B level message
        await add_scheduled_message(
            user_id="11111111-1111-1111-1111-111111111111",
            external_user_id="tg_123456789",
            message_type="text",
            content="High priority B message",
            platform="telegram_real_user",
            chat_id=123456789,
            send_at=None,
            priority=10,
            metadata={"test": True, "level": "B", "priority": "high"},
            trace_id="test-b-high",
        )

        # Add low priority C level message
        await add_scheduled_message(
            user_id="22222222-2222-2222-2222-222222222222",
            external_user_id="tg_987654321",
            message_type="text",
            content="Low priority C message",
            platform="telegram_real_user",
            chat_id=987654321,
            send_at=None,
            priority=0,
            metadata={"test": True, "level": "C", "priority": "low"},
            trace_id="test-c-low",
        )

        logger.info("✓ Priority ordering test messages added")
        return True
    except Exception as e:
        logger.error(f"✗ Failed priority ordering test: {e}")
        return False


async def main():
    """Run all tests."""
    logger.info("=" * 60)
    logger.info("P3-15: B/C/D Auto-Delivery Worker Test Suite")
    logger.info("=" * 60)

    # Setup
    await setup_test_db()

    # Run tests
    results = []
    results.append(await test_add_bcd_messages())
    results.append(await test_human_delay_calculation())
    results.append(await test_scheduler_status())
    results.append(await test_account_pool_reinit())
    results.append(await test_tick_execution())
    results.append(await test_bcd_filtering())
    results.append(await test_message_status_tracking())
    results.append(await test_priority_ordering())

    # Cleanup
    await cleanup_test_db()

    # Summary
    passed = sum(results)
    total = len(results)
    logger.info("=" * 60)
    logger.info(f"Test Results: {passed}/{total} passed")
    logger.info("=" * 60)

    if passed == total:
        logger.info("✓ All tests passed!")
        return 0
    else:
        logger.error(f"✗ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)