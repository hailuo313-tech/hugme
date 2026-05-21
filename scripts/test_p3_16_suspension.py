"""
P3-16: S/A suspension + draft with Top3 scripts test script.

This script tests the suspension functionality:
1. S/A level user detection
2. Handoff task creation
3. Draft generation with Top3 scripts
4. Countdown calculation
5. Draft expiration handling
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

# Add app directory to path
app_dir = Path(__file__).parent.parent / "app"
sys.path.insert(0, str(app_dir))

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal, engine
from services.suspension_service import (
    create_handoff_draft,
    get_draft_with_countdown,
    suspend_sa_message,
)


async def setup_test_db():
    """Setup test database tables and data."""
    async with engine.begin() as conn:
        # Add draft fields to handoff_tasks table
        migration_sql = Path(__file__).parent.parent / "scripts" / "migrations" / "add_handoff_draft_fields.sql"
        if migration_sql.exists():
            sql = migration_sql.read_text()
            await conn.execute(text(sql))
            logger.info("Added draft fields to handoff_tasks table")

        # Create test users with S/A levels
        await conn.execute(
            text(
                """
                INSERT INTO users (id, external_id, level, channel, created_at, updated_at)
                VALUES
                    ('11111111-1111-1111-1111-111111111111', 'tg_123456789', 'S', 'telegram_real_user', NOW(), NOW()),
                    ('22222222-2222-2222-2222-222222222222', 'tg_987654321', 'A', 'telegram_real_user', NOW(), NOW()),
                    ('33333333-3333-3333-3333-333333333333', 'tg_456789123', 'B', 'telegram_real_user', NOW(), NOW())
                ON CONFLICT (id) DO NOTHING
                """
            )
        )

        # Create test conversations
        await conn.execute(
            text(
                """
                INSERT INTO conversations (id, user_id, channel, created_at, updated_at)
                VALUES
                    ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '11111111-1111-1111-1111-111111111111', 'telegram_real_user', NOW(), NOW()),
                    ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', '22222222-2222-2222-2222-222222222222', 'telegram_real_user', NOW(), NOW()),
                    ('cccccccc-cccc-cccc-cccc-cccccccccccc', '33333333-3333-3333-3333-333333333333', 'telegram_real_user', NOW(), NOW())
                ON CONFLICT (id) DO NOTHING
                """
            )
        )

        logger.info("Created test users and conversations")


async def cleanup_test_db():
    """Cleanup test data."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("DELETE FROM handoff_tasks WHERE user_id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', '33333333-3333-3333-3333-333333333333')")
        )
        await session.commit()
        logger.info("Cleaned up test data")


async def test_sa_level_suspension():
    """Test suspending S level user message."""
    logger.info("Test 1: Suspend S level user message")
    try:
        async with AsyncSessionLocal() as session:
            result = await suspend_sa_message(
                db=session,
                conversation_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                query_text="用户询问如何升级会员",
                trigger_reason="TEST_SA_SUSPEND",
                countdown_seconds=120,
                trace_id="test-sa-suspend",
            )

            if result.get("success"):
                logger.info(f"✓ S level suspension successful: task_id={result.get('task_id')}")
                return True
            else:
                logger.warning(f"✗ S level suspension failed: {result.get('reason')}")
                return False
    except Exception as e:
        logger.error(f"✗ S level suspension test error: {e}")
        return False


async def test_a_level_suspension():
    """Test suspending A level user message."""
    logger.info("Test 2: Suspend A level user message")
    try:
        async with AsyncSessionLocal() as session:
            result = await suspend_sa_message(
                db=session,
                conversation_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                query_text="用户询问价格问题",
                trigger_reason="TEST_A_SUSPEND",
                countdown_seconds=90,
                trace_id="test-a-suspend",
            )

            if result.get("success"):
                logger.info(f"✓ A level suspension successful: task_id={result.get('task_id')}")
                return True
            else:
                logger.warning(f"✗ A level suspension failed: {result.get('reason')}")
                return False
    except Exception as e:
        logger.error(f"✗ A level suspension test error: {e}")
        return False


async def test_b_level_rejection():
    """Test that B level user is rejected."""
    logger.info("Test 3: B level user should be rejected")
    try:
        async with AsyncSessionLocal() as session:
            result = await suspend_sa_message(
                db=session,
                conversation_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
                query_text="用户询问一般问题",
                trigger_reason="TEST_B_SUSPEND",
                countdown_seconds=120,
                trace_id="test-b-suspend",
            )

            if not result.get("success") and "not S or A level" in result.get("reason", ""):
                logger.info("✓ B level correctly rejected")
                return True
            else:
                logger.warning(f"✗ B level should be rejected but got: {result}")
                return False
    except Exception as e:
        logger.error(f"✗ B level rejection test error: {e}")
        return False


async def test_draft_generation():
    """Test draft generation with Top3 scripts."""
    logger.info("Test 4: Draft generation with Top3 scripts")
    try:
        async with AsyncSessionLocal() as session:
            # First create a handoff task
            task_id = str(uuid4())
            await session.execute(
                text("""
                    INSERT INTO handoff_tasks (id, user_id, conversation_id, priority, trigger_reason, status)
                    VALUES (:id, '11111111-1111-1111-1111-111111111111', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'P1', 'TEST', 'pending')
                """),
                {"id": task_id}
            )
            await session.commit()

            # Create draft
            result = await create_handoff_draft(
                db=session,
                task_id=task_id,
                query_text="用户询问会员升级",
                countdown_seconds=120,
                trace_id="test-draft-gen",
            )

            if result.get("success"):
                logger.info(
                    f"✓ Draft generation successful: "
                    f"script_count={len(result.get('script_ids', []))}, "
                    f"countdown={result.get('countdown_seconds')}s"
                )
                return True
            else:
                logger.warning(f"✗ Draft generation failed: {result.get('reason')}")
                return False
    except Exception as e:
        logger.error(f"✗ Draft generation test error: {e}")
        return False


async def test_countdown_calculation():
    """Test countdown calculation."""
    logger.info("Test 5: Countdown calculation")
    try:
        async with AsyncSessionLocal() as session:
            # Create a handoff task with draft
            task_id = str(uuid4())
            await session.execute(
                text("""
                    INSERT INTO handoff_tasks (id, user_id, conversation_id, priority, trigger_reason, status,
                                              draft_content, draft_script_ids, draft_created_at, draft_expires_at, countdown_seconds)
                    VALUES (:id, '11111111-1111-1111-1111-111111111111', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'P1', 'TEST', 'pending',
                            'Test draft', ARRAY['script1', 'script2']::UUID[], NOW(), NOW() + INTERVAL '60 seconds', 60)
                """),
                {"id": task_id}
            )
            await session.commit()

            # Get draft with countdown
            result = await get_draft_with_countdown(
                db=session,
                task_id=task_id,
                trace_id="test-countdown",
            )

            if result.get("success") and result.get("has_draft"):
                remaining = result.get("remaining_seconds", 0)
                logger.info(f"✓ Countdown calculation successful: remaining={remaining}s")
                return True
            else:
                logger.warning(f"✗ Countdown calculation failed: {result}")
                return False
    except Exception as e:
        logger.error(f"✗ Countdown calculation test error: {e}")
        return False


async def test_draft_expiration():
    """Test draft expiration handling."""
    logger.info("Test 6: Draft expiration handling")
    try:
        async with AsyncSessionLocal() as session:
            # Create a handoff task with expired draft
            task_id = str(uuid4())
            await session.execute(
                text("""
                    INSERT INTO handoff_tasks (id, user_id, conversation_id, priority, trigger_reason, status,
                                              draft_content, draft_script_ids, draft_created_at, draft_expires_at, countdown_seconds)
                    VALUES (:id, '11111111-1111-1111-1111-111111111111', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'P1', 'TEST', 'pending',
                            'Test draft', ARRAY['script1']::UUID[], NOW() - INTERVAL '10 seconds', NOW() - INTERVAL '10 seconds', 60)
                """),
                {"id": task_id}
            )
            await session.commit()

            # Get draft with countdown
            result = await get_draft_with_countdown(
                db=session,
                task_id=task_id,
                trace_id="test-expiration",
            )

            if result.get("success") and result.get("has_draft"):
                is_expired = result.get("is_expired", False)
                if is_expired:
                    logger.info("✓ Draft correctly marked as expired")
                    return True
                else:
                    logger.warning("✗ Draft should be expired")
                    return False
            else:
                logger.warning(f"✗ Draft expiration test failed: {result}")
                return False
    except Exception as e:
        logger.error(f"✗ Draft expiration test error: {e}")
        return False


async def test_existing_task_update():
    """Test updating existing handoff task with new draft."""
    logger.info("Test 7: Update existing handoff task")
    try:
        async with AsyncSessionLocal() as session:
            # First suspend to create task
            result1 = await suspend_sa_message(
                db=session,
                conversation_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                query_text="第一次查询",
                trigger_reason="TEST_EXISTING_TASK",
                countdown_seconds=120,
                trace_id="test-existing-1",
            )

            if not result1.get("success"):
                logger.warning(f"✗ Failed to create initial task: {result1.get('reason')}")
                return False

            task_id = result1.get("task_id")

            # Suspend again to update existing task
            result2 = await suspend_sa_message(
                db=session,
                conversation_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                query_text="第二次查询",
                trigger_reason="TEST_EXISTING_TASK",
                countdown_seconds=90,
                trace_id="test-existing-2",
            )

            if result2.get("success") and result2.get("action") == "updated_existing_task":
                logger.info("✓ Existing task updated successfully")
                return True
            else:
                logger.warning(f"✗ Failed to update existing task: {result2}")
                return False
    except Exception as e:
        logger.error(f"✗ Existing task update test error: {e}")
        return False


async def test_draft_content_format():
    """Test draft content formatting."""
    logger.info("Test 8: Draft content formatting")
    try:
        async with AsyncSessionLocal() as session:
            # Create a handoff task
            task_id = str(uuid4())
            await session.execute(
                text("""
                    INSERT INTO handoff_tasks (id, user_id, conversation_id, priority, trigger_reason, status)
                    VALUES (:id, '11111111-1111-1111-1111-111111111111', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'P1', 'TEST', 'pending')
                """),
                {"id": task_id}
            )
            await session.commit()

            # Create draft
            result = await create_handoff_draft(
                db=session,
                task_id=task_id,
                query_text="用户询问会员权益",
                countdown_seconds=120,
                trace_id="test-format",
            )

            if result.get("success"):
                draft_content = result.get("draft_content", "")
                if "推荐话术 Top3" in draft_content or "暂无推荐话术" in draft_content:
                    logger.info(f"✓ Draft content format correct: {draft_content[:100]}...")
                    return True
                else:
                    logger.warning(f"✗ Draft content format incorrect: {draft_content}")
                    return False
            else:
                logger.warning(f"✗ Draft format test failed: {result.get('reason')}")
                return False
    except Exception as e:
        logger.error(f"✗ Draft format test error: {e}")
        return False


async def main():
    """Run all tests."""
    logger.info("=" * 60)
    logger.info("P3-16: S/A Suspension + Draft Test Suite")
    logger.info("=" * 60)

    # Setup
    await setup_test_db()

    # Run tests
    results = []
    results.append(await test_sa_level_suspension())
    results.append(await test_a_level_suspension())
    results.append(await test_b_level_rejection())
    results.append(await test_draft_generation())
    results.append(await test_countdown_calculation())
    results.append(await test_draft_expiration())
    results.append(await test_existing_task_update())
    results.append(await test_draft_content_format())

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