# P2-12 MTProto Level Archive Evidence

Status: evidence gate defined for staging/production.

P2-12 acceptance says MTProto real-user inbound messages must be graded
correctly. Unit smoke is not enough; keep a sanitized archive from staging or
production and validate it with the repository checker.

## Evidence Requirements

The archive must contain at least one `telegram_real_user` inbound event with:

| Field | Required | Notes |
| --- | --- | --- |
| platform | yes | Must be `telegram_real_user` |
| external_user_id | yes | Opaque or hashed Telegram user key |
| account_id | yes | AccountPool account id used by MTProto |
| message_type | yes | `text`, `photo`, `voice`, etc. |
| metadata.user_level | yes | One of `S/A/B/C/D` |
| metadata.chat_route | yes | Must match the level route map |
| metadata.level_reason | yes | Reason from `calc_user_level` |
| metadata.country_tier | yes | `T1`, `T2`, `T3`, or `unknown` |
| collected_at | yes | UTC evidence timestamp |
| environment | yes | `staging` or `production` |

Do not include raw message content, phone numbers, StringSession values, API
hashes, or user personal data.

## Verification Command

```powershell
python scripts/check_p2_12_mtproto_level_archive.py evidence/p2_12_mtproto_level_archive.json
```

Expected output:

```text
P2-12 PASS: MTProto real-user inbound level archive is valid
```

## Route Map

| Level | chat_route |
| --- | --- |
| S | manual_premium |
| A | manual_premium |
| B | ai_assisted |
| C | ai_auto |
| D | ai_auto |
