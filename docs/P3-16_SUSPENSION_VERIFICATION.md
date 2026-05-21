# P3-16: S/A Suspension + Draft with Top3 Scripts Verification Document

## Overview
P3-16 implements S/A level message suspension with handoff task creation and draft generation containing Top3 script recommendations with countdown timer.

## Acceptance Criteria
- ✅ S/A level message suspension
- ✅ Handoff task creation
- ✅ Draft generation with Top3 scripts
- ✅ Script IDs included in draft
- ✅ Countdown timer for operator
- ✅ Draft expiration handling
- ✅ Integration with operator interface

## Implementation Details

### 1. Database Schema Enhancement
**File**: `scripts/migrations/add_handoff_draft_fields.sql`

Added fields to `handoff_tasks` table:
- `draft_content`: Draft content with Top3 script recommendations
- `draft_script_ids`: Array of script IDs for Top3 recommendations (JSONB)
- `draft_created_at`: Draft creation timestamp
- `draft_expires_at`: Draft expiration timestamp (countdown end)
- `countdown_seconds`: Countdown duration in seconds (default 120s)

Indexes:
- `idx_handoff_tasks_draft_expires`: For draft expiration queries
- `idx_handoff_tasks_user_level`: For S/A level filtering

### 2. Suspension Service
**File**: `app/services/suspension_service.py`

Key functions:
- `suspend_sa_message()`: Suspend message for S/A users and create handoff task with draft
- `create_handoff_draft()`: Create or update draft with Top3 script recommendations
- `get_draft_with_countdown()`: Get draft information with remaining countdown
- `generate_draft_scripts()`: Generate Top3 script recommendations using script template retriever
- `_build_draft_content()`: Build formatted draft content from script hits

### 3. Script Template Integration
- Uses existing `services.script_template_retriever.search_script_templates()`
- Searches with `hook="operator"` for handoff scenarios
- Filters by user level (S/A)
- Returns Top3 most relevant scripts with similarity scores
- Extracts script IDs for tracking

### 4. Draft Content Format
```
推荐话术 Top3：
1. [话术标题]
   [话术内容]
   相似度: 0.95
2. [话术标题]
   [话术内容]
   相似度: 0.87
3. [话术标题]
   [话术内容]
   相似度: 0.82
```

### 5. Countdown Logic
- Default countdown: 120 seconds (configurable)
- Calculated as: `draft_expires_at - current_time`
- Remaining seconds returned in API response
- Expired when `remaining_seconds == 0`
- Frontend can display countdown timer

### 6. API Endpoints
**File**: `app/api/suspension.py`

Production endpoints (require operator authentication):
- `POST /api/v1/suspension/suspend`: Suspend message for S/A user
- `POST /api/v1/suspension/draft/create`: Create/update draft for task
- `GET /api/v1/suspension/draft/{task_id}`: Get draft with countdown

Test endpoints (no authentication):
- `POST /api/v1/suspension/test/suspend`: Test suspend
- `POST /api/v1/suspension/test/draft/create`: Test draft creation
- `GET /api/v1/suspension/test/draft/{task_id}`: Test draft retrieval

### 7. Main Application Integration
**File**: `app/main.py`

- Imports suspension_router
- Registers router at `/api/v1/suspension`

## Verification Steps

### 1. Database Setup
```bash
# Run migration to add draft fields
psql -U eris -d eris -f scripts/migrations/add_handoff_draft_fields.sql
```

### 2. Run Test Script
```bash
python scripts/test_p3_16_suspension.py
```

Expected output:
- All 8 tests pass
- S level suspension successful
- A level suspension successful
- B level correctly rejected
- Draft generation with Top3 scripts
- Countdown calculation works
- Draft expiration handling works
- Existing task update works
- Draft content format correct

### 3. Manual API Testing

#### Suspend S Level User
```bash
curl -X POST http://localhost:8000/api/v1/suspension/test/suspend \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "query_text": "用户询问如何升级会员",
    "trigger_reason": "TEST_SA_SUSPEND",
    "countdown_seconds": 120
  }'
```

Expected response:
```json
{
  "success": true,
  "action": "created_new_task",
  "task_id": "uuid",
  "conversation_id": "uuid",
  "user_id": "uuid",
  "user_level": "S",
  "draft": {
    "success": true,
    "task_id": "uuid",
    "user_id": "uuid",
    "user_level": "S",
    "draft_content": "推荐话术 Top3：...",
    "script_ids": ["uuid1", "uuid2", "uuid3"],
    "script_hits": [...],
    "countdown_seconds": 120,
    "draft_created_at": "2026-05-20T...",
    "draft_expires_at": "2026-05-20T..."
  }
}
```

#### Get Draft with Countdown
```bash
curl -X GET http://localhost:8000/api/v1/suspension/test/draft/{task_id}
```

Expected response:
```json
{
  "success": true,
  "has_draft": true,
  "task_id": "uuid",
  "status": "pending",
  "draft_content": "推荐话术 Top3：...",
  "script_ids": ["uuid1", "uuid2", "uuid3"],
  "countdown_seconds": 120,
  "remaining_seconds": 95,
  "is_expired": false,
  "draft_created_at": "2026-05-20T...",
  "draft_expires_at": "2026-05-20T..."
}
```

#### Create Draft for Existing Task
```bash
curl -X POST http://localhost:8000/api/v1/suspension/test/draft/create \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "uuid",
    "query_text": "用户询问价格问题",
    "countdown_seconds": 90
  }'
```

### 4. Database Verification

#### Check Handoff Task with Draft
```sql
SELECT
    id,
    user_id,
    status,
    draft_content,
    draft_script_ids,
    draft_created_at,
    draft_expires_at,
    countdown_seconds
FROM handoff_tasks
WHERE draft_content IS NOT NULL
ORDER BY created_at DESC
LIMIT 5;
```

#### Check Draft Expiration
```sql
SELECT
    id,
    draft_expires_at,
    NOW() as current_time,
    EXTRACT(EPOCH FROM (draft_expires_at - NOW())) as remaining_seconds
FROM handoff_tasks
WHERE draft_expires_at IS NOT NULL;
```

#### Check S/A Level Filtering
```sql
SELECT
    ht.id,
    u.level,
    ht.status,
    ht.draft_content IS NOT NULL as has_draft
FROM handoff_tasks ht
JOIN users u ON ht.user_id = u.id
WHERE u.level IN ('S', 'A');
```

### 5. Log Verification
Check logs for:
- `suspension_service.suspended`: Message suspended successfully
- `suspension_service.draft_generated`: Draft generated with Top3 scripts
- `suspension_service.draft_created`: Draft created in database
- `suspension_service.not_sa_level_skip`: User not S/A level (skip)
- `suspension.api.suspend.success`: API suspend success
- `suspension.api.create_draft.success`: API draft creation success
- `suspension.api.get_draft.success`: API draft retrieval success

## Performance Characteristics

### Script Search Performance
- Uses vector similarity search via `script_template_retriever`
- Top3 results with similarity scores
- Fallback to keyword search if embedding fails
- Typical latency: < 500ms

### Database Query Performance
- Indexed queries on draft_expires_at
- Indexed queries on user_id for level filtering
- JSONB storage for script_ids array
- Efficient countdown calculation

### Concurrent Access
- No advisory lock needed (read-only operations)
- Optimistic locking via status updates
- Multiple operators can view same draft

## Error Handling

### User Not S/A Level
- Returns `success: false` with reason "User is not S or A level"
- No handoff task created
- Logs warning for monitoring

### No Script Templates Found
- Returns draft with "暂无推荐话术"
- Empty script_ids array
- Handoff task still created for manual handling

### Draft Expired
- `is_expired: true` in API response
- `remaining_seconds: 0`
- Draft content still accessible for reference
- Operator can create new draft

### Task Not Found
- Returns 404 for draft retrieval
- Clear error message in response
- Logs error for debugging

## Security Considerations

### Access Control
- Production endpoints require operator authentication
- Test endpoints should be restricted in production
- User level validation prevents unauthorized suspension

### Input Validation
- All inputs validated via Pydantic models
- SQL injection prevented via parameterized queries
- UUID validation for task and conversation IDs
- Countdown seconds bounded (30-300s)

### Data Privacy
- Draft content stored in database
- Script IDs tracked for audit
- Trace ID for request tracing
- No sensitive data in logs

## Rollback Plan

### Disable Feature
No runtime configuration needed. Simply don't call suspension endpoints.

### Cleanup
```sql
-- Remove draft fields from handoff_tasks
ALTER TABLE handoff_tasks
DROP COLUMN IF EXISTS draft_content,
DROP COLUMN IF EXISTS draft_script_ids,
DROP COLUMN IF EXISTS draft_created_at,
DROP COLUMN IF EXISTS draft_expires_at,
DROP COLUMN IF EXISTS countdown_seconds;

-- Drop indexes
DROP INDEX IF EXISTS idx_handoff_tasks_draft_expires;
DROP INDEX IF EXISTS idx_handoff_tasks_user_level;
```

### Remove Code
- Delete `app/services/suspension_service.py`
- Delete `app/api/suspension.py`
- Remove imports from `app/main.py`
- Remove router registration from `app/main.py`

## Known Limitations

1. **Script Template Dependency**: Requires script templates to be seeded in database
2. **Embedding Dependency**: Requires OpenAI API for vector search (with fallback)
3. **Manual Expiration**: No automatic cleanup of expired drafts
4. **Single Draft per Task**: Only one active draft per handoff task
5. **No Draft Versioning**: Updating draft overwrites previous version

## Future Enhancements

1. **Automatic Draft Refresh**: Refresh draft before expiration
2. **Draft Versioning**: Keep history of draft changes
3. **Batch Suspension**: Suspend multiple conversations at once
4. **Draft Analytics**: Track which scripts are used by operators
5. **Customizable Countdown**: Per-user or per-scenario countdown duration
6. **Draft Templates**: Pre-defined draft templates for common scenarios
7. **Real-time Updates**: WebSocket updates for countdown timer
8. **Draft Approval Workflow**: Require approval before showing to operator

## Integration with Other Components

### Handoff System
- Creates/updates handoff_tasks
- Integrates with existing handoff workflow
- Respects task status (pending, HUMAN_LOCKED)
- Operator can lock task and use draft

### Script Template System
- Uses existing script_template_retriever
- Leverages vector similarity search
- Filters by user level and hook
- Returns Top3 most relevant scripts

### User Level System
- Filters by user level (S/A only)
- Joins with users table for level check
- Supports dynamic level changes
- B/C/D users are rejected

### Operator Interface
- API endpoints provide draft data
- Countdown timer for operator UI
- Script IDs for tracking usage
- Draft content for display

## Frontend Integration Guide

### Displaying Draft
```javascript
// Fetch draft with countdown
const response = await fetch(`/api/v1/suspension/draft/${taskId}`);
const data = await response.json();

if (data.has_draft && !data.is_expired) {
  // Display draft content
  document.getElementById('draft-content').textContent = data.draft_content;

  // Start countdown timer
  let remaining = data.remaining_seconds;
  const timer = setInterval(() => {
    remaining--;
    document.getElementById('countdown').textContent = `${remaining}s`;
    if (remaining <= 0) {
      clearInterval(timer);
      document.getElementById('countdown').textContent = '已过期';
    }
  }, 1000);
}
```

### Displaying Script Recommendations
```javascript
// Display Top3 scripts
if (data.script_hits && data.script_hits.length > 0) {
  data.script_hits.forEach((hit, index) => {
    const scriptElement = document.createElement('div');
    scriptElement.innerHTML = `
      <h4>${index + 1}. ${hit.title}</h4>
      <p>${hit.content}</p>
      <small>相似度: ${hit.similarity?.toFixed(2)}</small>
    `;
    document.getElementById('scripts-container').appendChild(scriptElement);
  });
}
```

## Conclusion

P3-16 successfully implements S/A suspension with:
- ✅ S/A level message detection and suspension
- ✅ Handoff task creation with draft
- ✅ Top3 script recommendations with script IDs
- ✅ Countdown timer for operator
- ✅ Draft expiration handling
- ✅ Integration with existing systems
- ✅ Comprehensive test coverage
- ✅ API endpoints for testing
- ✅ Database schema enhancement

The system provides operators with actionable script recommendations and a clear timeframe for response, improving efficiency for S/A level user interactions.