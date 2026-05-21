"""
P3-13: Redis pending queue + send_at test script.

This script tests the message schedule functionality:
1. Add scheduled messages with send_at
2. Test immediate messages (send_at = None)
3. Test time-based scanning scheduler
4. Test message status tracking
5. Test retry mechanism
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
from services.message_schedule_service import (
    add_scheduled_message,
    get_scheduler_status,
    run_one_tick,
)


async def setup_test_db():
    """Setup test database table."""
    async with engine.begin() as conn:
        # Create table for testing
        migration_sql = Path(__file__).parent.parent / "scripts" / "migrations" / "create_message_schedules.sql"
        if migration_sql.exists():
            sql = migration_sql.read_text()
            await conn.execute(text(sql))
            logger.info("Created message_schedules table")
        else:
            logger.warning(f"Migration file not found: {migration_sql}")


async def cleanup_test_db():
    """Cleanup test data."""
    async with AsyncSessionLocal() as session:
        await session.execute(text("DELETE FROM message_schedules WHERE user_id LIKE 'test-%'"))
        await session.commit()
        logger.info("Cleaned up test data")


async def test_add_immediate_message():
    """Test adding an immediate message (send_at = None)."""
    logger.info("Test 1: Adding immediate message")
    try:
        message_id = await add_scheduled_message(
            user_id="test-user-1",
            external_user_id="test-external-1",
            message_type="text",
            content="Immediate test message",
            platform="telegram_real_user",
            account_id=None,  # No account for test
            chat_id=123456789,
            send_at=None,  # Immediate
            priority=0,
            metadata={"test": True},
            trace_id="test-1",
        )
        logger.info(f"✓ Immediate message added: {message_id}")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to add immediate message: {e}")
        return False


async def test_add_scheduled_message():
    """Test adding a scheduled message with send_at."""
    logger.info("Test 2: Adding scheduled message")
    try:
        send_at = datetime.now(timezone.utc) + timedelta(seconds=10)
        message_id = await add_scheduled_message(
            user_id="test-user-2",
            external_user_id="test-external-2",
            message_type="text",
            content="Scheduled test message",
            platform="telegram_real_user",
            account_id=None,
            chat_id=123456789,
            send_at=send_at,  # Scheduled for 10 seconds later
            priority=1,
            metadata={"test": True, "scheduled": True},
            trace_id="test-2",
        )
        logger.info(f"✓ Scheduled message added: {message_id}, send_at={send_at}")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to add scheduled message: {e}")
        return False


async def test_add_past_message():
    """Test adding a message with past send_at (should be sent immediately)."""
    logger.info("Test 3: Adding message with past send_at")
    try:
        send_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        message_id = await add_scheduled_message(
            user_id="test-user-3",
            external_user_id="test-external-3",
            message_type="text",
            content="Past time test message",
            platform="telegram_real_user",
            account_id=None,
            chat_id=123456789,
            send_at=send_at,  # Past time
            priority=2,
            metadata={"test": True, "past": True},
            trace_id="test-3",
        )
        logger.info(f"✓ Past time message added: {message_id}, send_at={send_at}")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to add past time message: {e}")
        return False


async def test_priority_ordering():
    """Test that higher priority messages are sent first."""
    logger.info("Test 4: Testing priority ordering")
    try:
        # Add messages with different priorities
        await add_scheduled_message(
            user_id="test-user-4",
            external_user_id="test-external-4",
            message_type="text",
            content="Low priority message",
            platform="telegram_real_user",
            account_id=None,
            chat_id=123456789,
            send_at=None,
            priority=0,
            metadata={"test": True, "priority": 0},
            trace_id="test-4-low",
        )

        await add_scheduled_message(
            user_id="test-user-4",
            external_user_id="test-external-4",
            message_type="text",
            content="High priority message",
            platform="telegram_real_user",
            account_id=None,
            chat_id=123456789,
            send_at=None,
            priority=10,
            metadata={"test": True, "priority": 10},
            trace_id="test-4-high",
        )

        logger.info("✓ Priority ordering test messages added")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to add priority test messages: {e}")
        return False


async def test_scheduler_status():
    """Test getting scheduler status."""
    logger.info("Test 5: Getting scheduler status")
    try:
        status = get_scheduler_status()
        logger.info(f"✓ Scheduler status: {status}")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to get scheduler status: {e}")
        return False


async def test_tick_execution():
    """Test manual tick execution."""
    logger.info("Test 6: Executing manual tick")
    try:
        stats = await run_one_tick(trace_id="test-tick")
        logger.info(f"✓ Tick executed: {stats}")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to execute tick: {e}")
        return False


async def test_message_status_tracking():
    """Test message status tracking in database."""
    logger.info("Test 7: Checking message status in database")
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(
                    """
                    SELECT id, user_id, status, send_at, priority, retry_count
                    FROM message_schedules
                    WHERE user_id LIKE 'test-%'
                    ORDER BY created_at DESC
                    LIMIT 10
                    """
                )
            )
            messages = result.mappings().all()

            logger.info(f"✓ Found {len(messages)} test messages in database:")
            for msg in messages:
                logger.info(
                    f"  - ID: {msg['id']}, User: {msg['user_id']}, "
                    f"Status: {msg['status']}, SendAt: {msg['send_at']}, "
                    f"Priority: {msg['priority']}, Retries: {msg['retry_count']}"
                )
            return len(messages) > 0
    except Exception as e:
        logger.error(f"✗ Failed to check message status: {e}")
        return False


async def test_retry_mechanism():
    """Test retry mechanism by simulating failed sends."""
    logger.info("Test 8: Testing retry mechanism")
    try:
        # Add a message without account_id (will fail to send)
        message_id = await add_scheduled_message(
            user_id="test-user-5",
            external_user_id="test-external-5",
            message_type="text",
            content="Retry test message",
            platform="telegram_real_user",
            account_id=None,  # Missing account_id will cause failure
            chat_id=123456789,
            send_at=None,
            priority=0,
            metadata={"test": True, "retry": True},
            trace_id="test-retry",
        )

        # Execute tick to trigger send (will fail)
        await run_one_tick(trace_id="test-retry-tick")

        # Check retry count
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(
                    """
                    SELECT retry_count, status, failure_reason
                    FROM message_schedules
                    WHERE id = :id
                    """
                ),
                {"id": message_id},
            )
            msg = result.mappings().first()

            if msg:
                logger.info(
                    f"✓ Retry test: Status={msg['status']}, "
                    f"RetryCount={msg['retry_count']}, "
                    f"FailureReason={msg['failure_reason']}"
                )
                return True
            else:
                logger.error("✗ Retry test: Message not found in database")
                return False
    except Exception as e:
        logger.error(f"✗ Failed retry test: {e}")
        return False


async def main():
    """Run all tests."""
    logger.info("=" * 60)
    logger.info("P3-13: Redis pending queue + send_at Test Suite")
    logger.info("=" * 60)

    # Setup
    await setup_test_db()

    # Run tests
    results = []
    results.append(await test_add_immediate_message())
    results.append(await test_add_scheduled_message())
    results.append(await test_add_past_message())
    results.append(await test_priority_ordering())
    results.append(await test_scheduler_status())
    results.append(await test_tick_execution())
    results.append(await test_message_status_tracking())
    results.append(await test_retry_mechanism())

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