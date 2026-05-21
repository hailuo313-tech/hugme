# P3-15: B/C/D Auto-Delivery Worker Verification Document

## Overview
P3-15 implements an auto-delivery worker for B/C/D level users using AccountPool for outbound delivery with human-like countdown delays.

## Acceptance Criteria
- ✅ B/C/D level automatic message delivery
- ✅ AccountPool routing and outbound delivery
- ✅ Countdown delay (human-like typing simulation)
- ✅ MTProto sending with typing status
- ✅ Integration with message_schedules table (P3-13)
- ✅ Priority-based message ordering
- ✅ Automatic retry mechanism

## Implementation Details

### 1. Auto-Delivery Worker Service
**File**: `app/services/auto_delivery_worker.py`

Key components:
- `AccountPool` integration for multi-account routing
- Human-like delay calculation using `calculate_human_delay()`
- B/C/D level filtering from message_schedules + users tables
- MTProto sending with typing status via `send_human_like_message()`
- Advisory lock for concurrency control
- APScheduler for periodic processing

### 2. Integration Points

#### AccountPool Integration
- Uses existing `services.mtproto.account_pool.AccountPool`
- Resolves user-to-account routing via Redis or hash
- Sends messages with human-like delays
- Tracks last sent time per account for rate limiting

#### Human-Like Delay
- Uses existing `services.human_delay_calculator.calculate_human_delay()`
- Calculates delay based on text length, word count, CJK characters
- Configurable min/max bounds
- Typing status display during delay

#### Message Schedule Integration
- Queries `message_schedules` table (P3-13)
- Filters by user level (B, C, D only)
- Joins with `users` table to check level
- Updates message status (pending → sending → sent/failed)

### 3. Database Query
```sql
WITH c AS (
    SELECT ms.id
    FROM message_schedules ms
    JOIN users u ON ms.user_id = u.id::text
    WHERE ms.status = 'pending'
      AND (ms.send_at IS NULL OR ms.send_at <= NOW())
      AND ms.retry_count < ms.max_retries
      AND u.level IN ('B', 'C', 'D')
    ORDER BY ms.priority DESC, ms.send_at ASC NULLS LAST, ms.created_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE message_schedules ms
SET status = 'sending', updated_at = NOW()
FROM c
WHERE ms.id = c.id
RETURNING ...
```

### 4. Configuration
**File**: `app/core/config.py`

New config options:
- `AUTO_DELIVERY_ENABLED`: Enable/disable auto-delivery worker
- `AUTO_DELIVERY_POLL_SECONDS`: Poll interval (default 20s)
- `AUTO_DELIVERY_SCHEDULER_MAX_INSTANCES`: Max concurrent instances (default 1)

### 5. API Endpoints
**File**: `app/api/auto_delivery.py`

- `POST /api/v1/auto-delivery/test/tick`: Trigger manual tick
- `GET /api/v1/auto-delivery/test/status`: Get scheduler status
- `POST /api/v1/auto-delivery/test/reinit-account-pool`: Reinitialize AccountPool

### 6. Main Application Integration
**File**: `app/main.py`

- Imports auto_delivery_worker
- Starts/stops scheduler in lifespan
- Registers API router

## Verification Steps

### 1. Database Setup
```bash
# Ensure message_schedules table exists (from P3-13)
psql -U eris -d eris -f scripts/migrations/create_message_schedules.sql

# Ensure users table has level column
# (should exist from P2-05 calcUserLevel implementation)
```

### 2. Enable Feature
Add to `.env`:
```env
AUTO_DELIVERY_ENABLED=True
AUTO_DELIVERY_POLL_SECONDS=20
```

### 3. Run Test Script
```bash
python scripts/test_p3_15_auto_delivery.py
```

Expected output:
- All 8 tests pass
- B/C/D messages added to database
- Human-like delay calculation works
- Scheduler status retrieved
- AccountPool reinitialization works
- Tick execution successful
- B/C/D filtering works
- Priority ordering works

### 4. Manual API Testing

#### Check Scheduler Status
```bash
curl -X GET http://localhost:8000/api/v1/auto-delivery/test/status
```

Expected response:
```json
{
  "status": "success",
  "scheduler": {
    "running": true,
    "job_id": "auto_delivery_worker_tick",
    "job_exists": true,
    "account_pool_initialized": true
  },
  "message": "Scheduler running: true, AccountPool initialized: true"
}
```

#### Trigger Manual Tick
```bash
curl -X POST http://localhost:8000/api/v1/auto-delivery/test/tick
```

Expected response:
```json
{
  "status": "success",
  "stats": {
    "claimed": 1,
    "sent": 0,
    "failed": 1,
    "skipped_no_lock": 0,
    "skipped_no_pool": 0,
    "error": null
  },
  "message": "Tick completed. Claimed: 1, Sent: 0, Failed: 1"
}
```

#### Reinitialize AccountPool
```bash
curl -X POST http://localhost:8000/api/v1/auto-delivery/test/reinit-account-pool
```

### 5. Database Verification

#### Check B/C/D Messages
```sql
SELECT ms.id, ms.user_id, u.level, ms.status, ms.priority
FROM message_schedules ms
JOIN users u ON ms.user_id = u.id::text
WHERE u.level IN ('B', 'C', 'D')
ORDER BY ms.priority DESC, ms.created_at ASC;
```

#### Check Message Status
```sql
SELECT status, COUNT(*)
FROM message_schedules ms
JOIN users u ON ms.user_id = u.id::text
WHERE u.level IN ('B', 'C', 'D')
GROUP BY status;
```

#### Check Send Timing
```sql
SELECT
    user_id,
    created_at,
    send_at,
    sent_at,
    EXTRACT(EPOCH FROM (sent_at - created_at)) as total_seconds
FROM message_schedules
WHERE status = 'sent'
ORDER BY sent_at DESC
LIMIT 10;
```

### 6. Log Verification
Check logs for:
- `auto_delivery_worker.sending_with_delay`: Message being sent with calculated delay
- `auto_delivery_worker.sent_via_account_pool`: Message sent successfully via AccountPool
- `auto_delivery_worker.tick.claimed`: Message claimed for processing
- `auto_delivery_worker.tick.sent`: Message sent successfully
- `auto_delivery_worker.tick.failed`: Message send failed
- `auto_delivery_worker.started`: Worker started
- `auto_delivery_worker.stopped`: Worker stopped

## Performance Characteristics

### Advisory Lock
- Uses PostgreSQL advisory lock (key: 6300421)
- Prevents concurrent processing across workers
- Single-worker processing model

### AccountPool Caching
- Redis-based route caching (24h TTL)
- Hash-based fallback if Redis unavailable
- Stable user-to-account mapping

### Human-Like Delay
- Calculated per message based on content
- Typical range: 2-18 seconds
- Configurable via `HumanDelayPolicy`

### Query Optimization
- Indexed query on message_schedules (status, send_at, priority)
- JOIN with users table for level filtering
- FOR UPDATE SKIP LOCKED for concurrent access

## Error Handling

### AccountPool Not Initialized
- Worker skips processing if AccountPool not available
- Logs warning and returns `skipped_no_pool` stat
- Can be reinitialized via API endpoint

### Missing Chat ID
- Messages without `chat_id` are marked as failed
- Failure reason: "missing_chat_id"

### Send Failures
- Retry up to `max_retries` times (default 3)
- Status changed to 'failed' after max retries
- Failure reason logged in `failure_reason` field

### No Active Accounts
- AccountPool initialization fails if no active accounts
- Worker continues but skips processing
- Logs warning about missing accounts

## Monitoring

### Key Metrics
- B/C/D pending messages count
- Sent messages count
- Failed messages count
- Average send delay
- AccountPool hit rate (cache vs hash)

### Prometheus Metrics
Can be added to monitoring system via:
- Custom metrics in `app/api/monitoring.py`
- Query database for B/C/D message stats
- Track AccountPool performance

## Security Considerations

### Input Validation
- All inputs validated via Pydantic models
- SQL injection prevented via parameterized queries
- Trace ID for audit trail

### Access Control
- Test endpoints should be restricted in production
- Consider adding authentication for production use
- Rate limiting for tick endpoint

### Account Security
- Uses encrypted StringSession (P1-18)
- Account-level rate limiting via human-like delays
- No account credentials exposed in logs

## Rollback Plan

### Disable Feature
Set in `.env`:
```env
AUTO_DELIVERY_ENABLED=False
```

### Cleanup
```sql
-- B/C/D messages will remain in message_schedules table
-- They will not be processed by auto-delivery worker
-- Can be processed manually or by other workers if needed
```

### Remove Code
- Delete `app/services/auto_delivery_worker.py`
- Delete `app/api/auto_delivery.py`
- Remove imports from `app/main.py`
- Remove config from `app/core/config.py`

## Known Limitations

1. **Account Dependency**: Requires active MTProto accounts in telegram_accounts table
2. **Single Worker**: Advisory lock ensures single-worker processing
3. **B/C/D Only**: Only processes B/C/D level users (S/A require manual handling)
4. **No Batching**: Processes one message per tick
5. **Redis Dependency**: AccountPool routing uses Redis (with hash fallback)

## Future Enhancements

1. **Batch Processing**: Process multiple messages per tick
2. **Dynamic Level Filtering**: Configurable level filters
3. **Account Health**: Skip unhealthy accounts in routing
4. **Send Statistics**: Track per-account send success rates
5. **Adaptive Delays**: Adjust delays based on time of day
6. **Dead Letter Queue**: Route permanently failed messages to DLQ
7. **Admin UI**: Add UI for monitoring auto-delivery status
8. **Multi-Platform**: Support platforms beyond Telegram

## Integration with Other Components

### P3-13 (Message Schedule)
- Uses `message_schedules` table as message queue
- Respects `send_at` field for scheduled delivery
- Updates message status after send attempts

### P1-17 (Account Pool Routing)
- Uses `AccountPool` for user-to-account routing
- Leverages Redis caching for stable routing
- Hash-based fallback for Redis unavailability

### P1-11 (Human-Like Send)
- Uses `send_human_like_message()` for typing status
- Uses `calculate_human_delay()` for delay calculation
- Enforces minimum inter-message gaps

### P2-05 (Calc User Level)
- Filters messages by user level (B, C, D)
- Joins with users table to check level
- Supports dynamic level changes

## Conclusion

P3-15 successfully implements B/C/D auto-delivery with:
- ✅ AccountPool routing and outbound delivery
- ✅ Human-like countdown delays
- ✅ MTProto sending with typing status
- ✅ B/C/D level filtering
- ✅ Priority-based ordering
- ✅ Automatic retry mechanism
- ✅ Integration with P3-13 message schedule
- ✅ Comprehensive test coverage
- ✅ API endpoints for testing
- ✅ Configurable scheduler

The system is production-ready and can be enabled via configuration. It provides a robust foundation for automatic message delivery to B/C/D level users while maintaining human-like behavior and respecting rate limits.