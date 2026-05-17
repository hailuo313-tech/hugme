# P2 Operator Quality Scores

`operator_quality_scores` records QA review results for operator handoff replies.
It is an operator/admin-only backend surface; Admin UI is intentionally out of
scope for this task.

## Endpoints

All endpoints require an operator JWT.

- `POST /api/v1/operator-quality`
- `GET /api/v1/operator-quality`
- `GET /api/v1/operator-quality/{quality_id}`
- `PATCH /api/v1/operator-quality/{quality_id}`

`reviewer_operator_id` is taken from the operator JWT `sub`. It is not accepted
from request bodies. PATCH updates `reviewer_operator_id` to the current
reviewer, so second-pass reviews have an auditable final reviewer.

Allowed `result` values:

- `passed`
- `needs_review`
- `failed`

Allowed `issue_tags` values:

- `tone_issue`
- `unsafe_advice`
- `policy_violation`
- `slow_response`
- `wrong_info`
- `missed_escalation`
- `other`

## Deploy

Run the idempotent migration before or during deployment:

```bash
cd /opt/eris
docker exec -i eris-postgres psql -U eris -d eris < scripts/migrations/p2_operator_quality_scores.sql
docker compose up -d --build api
```

Fresh environments also get the same DDL from `scripts/init.sql`.

## Smoke

Set:

```bash
BASE=http://127.0.0.1:8000
OPERATOR_JWT=<operator jwt>
OPERATOR_UUID=<operator uuid>
```

Create:

```bash
curl -s -X POST "$BASE/api/v1/operator-quality" \
  -H "Authorization: Bearer $OPERATOR_JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "operator_id": "'"$OPERATOR_UUID"'",
    "overall_score": 85,
    "empathy_score": 90,
    "accuracy_score": 80,
    "safety_score": 95,
    "timeliness_score": 75,
    "result": "passed",
    "issue_tags": [],
    "review_notes": "P2 smoke quality score"
  }'
```

Expected: HTTP `201`, JSON contains `id`, `overall_score=85`, and
`reviewer_operator_id`.

List:

```bash
curl -s "$BASE/api/v1/operator-quality?operator_id=$OPERATOR_UUID" \
  -H "Authorization: Bearer $OPERATOR_JWT"
```

Patch:

```bash
curl -s -X PATCH "$BASE/api/v1/operator-quality/$QUALITY_ID" \
  -H "Authorization: Bearer $OPERATOR_JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "overall_score": 90,
    "result": "passed",
    "review_notes": "Updated by smoke"
  }'
```

Validation:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST "$BASE/api/v1/operator-quality" \
  -H "Authorization: Bearer $OPERATOR_JWT" \
  -H "Content-Type: application/json" \
  -d '{"operator_id":"'"$OPERATOR_UUID"'","overall_score":101}'
```

Expected: `422`.

## SQL Checks

```sql
SELECT id, operator_id, reviewer_operator_id, overall_score, result, created_at
FROM operator_quality_scores
ORDER BY created_at DESC
LIMIT 10;
```

```sql
SELECT indexname
FROM pg_indexes
WHERE tablename = 'operator_quality_scores'
ORDER BY indexname;
```
