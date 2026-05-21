# P1-09 Online Real Account Evidence

Status: evidence gate defined for staging/production.

Acceptance requires at least one real Telegram account to be online. The
repository cannot store live phone numbers, StringSession values, or secrets, so
the durable artifact is a sanitized evidence export plus the checker below.

## Evidence Fields

Provide a JSON list or `{"accounts": [...]}` object with only these fields:

| Field | Required | Notes |
| --- | --- | --- |
| account_id | yes | Internal UUID or opaque id |
| is_bot | yes | Must be `false` for at least one row |
| is_active | yes | Must not be `false` |
| status | yes | `connected` or `online` passes |
| is_connected | optional | `true` passes even if status naming differs |
| collected_at | yes | UTC timestamp from staging/production |
| environment | yes | `staging` or `production` |

Do not include `phone`, `session_string`, session ciphertext, API hash, or user
personal data in the evidence file.

## Verification Command

```powershell
python scripts/check_p1_09_online_account.py evidence/p1_09_online_accounts.json
```

Expected output:

```text
P1-09 PASS: at least one active non-bot account is online
```

## Suggested Export Query

Run this against staging/production and save only the sanitized JSON:

```sql
SELECT
  id AS account_id,
  is_bot,
  is_active,
  status,
  NOW() AT TIME ZONE 'UTC' AS collected_at,
  'staging' AS environment
FROM telegram_accounts
WHERE is_bot = false
ORDER BY updated_at DESC;
```
