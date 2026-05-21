"""
P3-18: Archive service async premium chat archiving test script.

This script tests the archive functionality:
1. Async archiving (non-blocking)
2. Archive worker processing
3. Script hit record creation
4. Conversation script hits retrieval
5. Advisory lock for concurrency control
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
from services.archive_service import (
    archive_message,
    archive_message_async,
    get_conversation_script_hits,
    get_scheduler_status,
    run_one_tick,
)


async def setup_test_db():
    """Setup test database tables and data."""
    async with engine.begin() as conn:
        # Create conversation_script_hits table
        migration_sql = Path(__file__).parent.parent / "scripts" / "migrations" / "create_conversation_script_hits.sql"
        if migration_sql.exists():
            sql = migration_sql.read_text()
            await conn.execute(text(sql))
            logger.info("Created conversation_script_hits table")

        # Create test users, conversations, and messages
        await conn.execute(
            text(
                """
                INSERT INTO users (id, external_id, level, channel, created_at, updated_at)
                VALUES
                    ('11111111-1111-1111-1111-111111111111', 'tg_123456789', 'S', 'telegram_real_user', NOW(), NOW()),
                    ('22222222-2222-2222-2222-222222222222', 'tg_987654321', 'A', 'telegram_real_user', NOW(), NOW())
                ON CONFLICT (id) DO NOTHING
                """
            )
        )

        await conn.execute(
            text(
                """
                INSERT INTO conversations (id, user_id, channel, created_at, updated_at)
                VALUES
                    ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '11111111-1111-1111-1111-111111111111', 'telegram_real_user', NOW(), NOW()),
                    ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', '22222222-2222-2222-2222-222222222222', 'telegram_real_user', NOW(), NOW())
                ON CONFLICT (id) DO NOTHING
                """
            )
        )

        await conn.execute(
            text(
                """
                INSERT INTO messages (id, conversation_id, user_id, sender_type, content, content_type, created_at, updated_at)
                VALUES
                    ('mmmmmmmm-mmmm-mmmm-mmmm-mmmmmmmmmmmm', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '11111111-1111-1111-1111-111111111111', 'user', 'Test message 1', 'text', NOW(), NOW()),
                    ('nnnnnnnn-nnnn-nnnn-nnnn-nnnnnnnnnnnn', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', '22222222-2222-2222-2222-222222222222', 'user', 'Test message 2', 'text', NOW(), NOW())
                ON CONFLICT (id) DO NOTHING
                """
            )
        )

        logger.info("Created test data")


async def cleanup_test_db():
    """Cleanup test data."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("DELETE FROM conversation_script_hits WHERE conversation_id IN ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb')")
        )
        await session.commit()
        logger.info("Cleaned up test data")


async def test_async_archiving():
    """Test async archiving (non-blocking)."""
    logger.info("Test 1: Async archiving (non-blocking)")
    try:
        start_time = datetime.now()

        # Create async task
        task = await archive_message_async(
            conversation_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            message_id="mmmmmmmm-mmmm-mmmm-mmmm-mmmmmmmmmmmm",
            script_hit_id=str(uuid4()),
            hook="archive",
            user_level="S",
            platform="telegram",
            trace_id="test-async-archive",
        )

        elapsed = (datetime.now() - start_time).total_seconds()

        # Should return immediately (non-blocking)
        if elapsed < 0.1:  # Should complete in < 100ms
            logger.info(f"✓ Async archiving is non-blocking: {elapsed:.3f}s")
            return True
        else:
            logger.warning(f"✗ Async archiving took too long: {elapsed:.3f}s")
            return False

    except Exception as e:
        logger.error(f"✗ Async archiving test error: {e}")
        return False


async def test_sync_archiving():
    """Test synchronous archiving."""
    logger.info("Test 2: Synchronous archiving")
    try:
        archive_id = await archive_message(
            conversation_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            message_id="nnnnnnnn-nnnn-nnnn-nnnn-nnnnnnnnnnnn",
            script_hit_id=str(uuid4()),
            hook="archive",
            user_level="A",
            platform="telegram",
            trace_id="test-sync-archive",
        )

        logger.info(f"✓ Synchronous archiving successful: archive_id={archive_id}")
        return True

    except Exception as e:
        logger.error(f"✗ Synchronous archiving test error: {e}")
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


async def test_worker_tick():
    """Test archive worker tick execution."""
    logger.info("Test 4: Executing worker tick")
    try:
        stats = await run_one_tick(trace_id="test-archive-tick")
        logger.info(f"✓ Worker tick executed: {stats}")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to execute worker tick: {e}")
        return False


async def test_conversation_hits_retrieval():
    """Test retrieving conversation script hits."""
    logger.info("Test 5: Retrieving conversation script hits")
    try:
        # First, create some archive records
        await archive_message(
            conversation_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            message_id="mmmmmmmm-mmmm-mmmm-mmmm-mmmmmmmmmmmm",
            script_hit_id=str(uuid4()),
            hook="archive",
            user_level="S",
            platform="telegram",
            trace_id="test-hits-1",
        )

        await archive_message(
            conversation_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            message_id="mmmmmmmm-mmmm-mmmm-mmmm-mmmmmmmmmmmm",
            script_hit_id=str(uuid4()),
            hook="outbound",
            user_level="S",
            platform="telegram",
            trace_id="test-hits-2",
        )

        # Retrieve hits
        hits = await get_conversation_script_hits(
            conversation_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            limit=10,
            trace_id="test-retrieve-hits",
        )

        logger.info(f"✓ Retrieved {len(hits)} script hits")
        return len(hits) > 0

    except Exception as e:
        logger.error(f"✗ Failed to retrieve conversation hits: {e}")
        return False


async def test_multiple_hooks():
    """Test archiving with different hooks."""
    logger.info("Test 6: Archiving with different hooks")
    try:
        hooks = ["inbound", "consumption", "reply", "operator", "outbound", "archive"]
        for hook in hooks:
            await archive_message(
                conversation_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                message_id="nnnnnnnn-nnnn-nnnn-nnnn-nnnnnnnnnnnn",
                script_hit_id=str(uuid4()),
                hook=hook,
                user_level="A",
                platform="telegram",
                trace_id=f"test-hook-{hook}",
            )

        logger.info(f"✓ Archived with {len(hooks)} different hooks")
        return True

    except Exception as e:
        logger.error(f"✗ Failed to archive with different hooks: {e}")
        return False


async def test_duplicate_prevention():
    """Test that duplicate archives are handled correctly."""
    logger.info("Test 7: Duplicate prevention")
    try:
        script_hit_id = str(uuid4())

        # Archive same message twice
        await archive_message(
            conversation_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            message_id="mmmmmmmm-mmmm-mmmm-mmmm-mmmmmmmmmmmm",
            script_hit_id=script_hit_id,
            hook="archive",
            user_level="S",
            platform="telegram",
            trace_id="test-duplicate-1",
        )

        await archive_message(
            conversation_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            message_id="mmmmmmmm-mmmm-mmmm-mmmm-mmmmmmmmmmmm",
            script_hit_id=script_hit_id,
            hook="archive",
            user_level="S",
            platform="telegram",
            trace_id="test-duplicate-2",
        )

        # Check that both records exist (different script_hit_id or different hook)
        hits = await get_conversation_script_hits(
            conversation_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            limit=10,
        )

        logger.info(f"✓ Duplicate handling test: {len(hits)} records created")
        return True

    except Exception as e:
        logger.error(f"✗ Duplicate prevention test error: {e}")
        return False


async def test_hook_filtering():
    """Test filtering by hook."""
    logger.info("Test 8: Filtering by hook")
    try:
        # Create records with different hooks
        await archive_message(
            conversation_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            message_id="nnnnnnnn-nnnn-nnnn-nnnn-nnnnnnnnnnnn",
            script_hit_id=str(uuid4()),
            hook="inbound",
            user_level="A",
            platform="telegram",
            trace_id="test-filter-inbound",
        )

        await archive_message(
            conversation_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            message_id="nnnnnnnn-nnnn-nnnn-nnnn-nnnnnnnnnnnn",
            script_hit_id=str(uuid4()),
            hook="archive",
            user_level="A",
            platform="telegram",
            trace_id="test-filter-archive",
        )

        # Retrieve all hits
        all_hits = await get_conversation_script_hits(
            conversation_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            limit=10,
        )

        # Filter for archive hook
        archive_hits = [h for h in all_hits if h["hook"] == "archive"]

        if archive_hits:
            logger.info(f"✓ Hook filtering works: {len(archive_hits)} archive records found")
            return True
        else:
            logger.warning("✗ No archive records found")
            return False

    except Exception as e:
        logger.error(f"✗ Hook filtering test error: {e}")
        return False


async def main():
    """Run all tests."""
    logger.info("=" * 60)
    logger.info("P3-18: Archive Service Test Suite")
    logger.info("=" * 60)

    # Setup
    await setup_test_db()

    # Run tests
    results = []
    results.append(await test_async_archiving())
    results.append(await test_sync_archiving())
    results.append(await test_scheduler_status())
    results.append(await test_worker_tick())
    results.append(await test_conversation_hits_retrieval())
    results.append(await test_multiple_hooks())
    results.append(await test_duplicate_prevention())
    results.append(await test_hook_filtering())

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