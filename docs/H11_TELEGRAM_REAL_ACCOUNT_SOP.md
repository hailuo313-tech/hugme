# H-11 Telegram Real Account Operating SOP

Status: signed  
Task: H-11 - 审定 Telegram 真人账号运营规范（频率/批量/ToS）  
Signed on: 2026-05-20  
Signed by: ops_owner_pending_final_review

## Scope

This document signs the operating rules for Telegram real-user accounts used
through MTProto/Telethon. It complements C-15 security review by adding
operational frequency limits, batching rules, ToS guardrails, and pause
conditions.

Canonical machine-readable policy:

- `config/h11_telegram_real_account_sop.json`

References:

- `docs/MTProto_ENV_SETUP.md`
- `docs/MTProto_SECURITY_REVIEW_C15.md`
- `docs/sketches/telegram_accounts_P1-09.sql`
- `app/services/mtproto/account_routing.py`
- `app/services/mtproto/security_policy.py`

## Account Rules

- Use only Telegram accounts that the project is authorized to operate.
- Production session storage must be encrypted database ciphertext. Plaintext
  `TELEGRAM_SESSION_STRINGS` is forbidden in production.
- Each `account_id` must use an isolated Telethon client and isolated Redis
  prefixes.
- User-to-account routing must be stable; do not rotate accounts to bypass
  platform limits.
- StringSession, `api_hash`, Fernet keys, phone numbers, and auth keys must not
  be logged or committed.

## Signed Frequency Limits

| Limit | Per account |
|---|---:|
| New dialogs per hour | 5 |
| New dialogs per day | 30 |
| Outbound messages per minute | 3 |
| Outbound messages per hour | 60 |
| Outbound messages per day | 300 |
| Same-user messages per minute | 2 |
| Same-user messages per hour | 20 |
| Minimum typing delay | 2 seconds |
| Minimum inter-message delay | 8 seconds |

Pool-level limits:

| Limit | Pool |
|---|---:|
| Outbound messages per minute | 10 |
| New dialogs per hour | 10 |
| New dialogs per day | 60 |

Batching:

- Max batch size: 20.
- Batch cooldown: 20 minutes.
- Max parallel accounts per batch: 3.
- Marketing blast: disabled.
- Cold outreach: disabled.

## Allowed Use Cases

- Reply to user-initiated conversations.
- Operator-approved handoff replies.
- Low-frequency opted-in reactivation.
- Beta test conversations with invited users.

## Blocked Use Cases

- Cold outreach.
- Bulk marketing blast.
- Scraped lead messaging.
- Ban or flood-limit evasion.
- Adult or minor-risk solicitation.
- Messages to users who opted out.

## ToS Guardrails

- Do not buy, rent, scrape, or share Telegram accounts.
- Do not send spam, unsolicited bulk outreach, deceptive messages, phishing,
  malware, adult solicitation, or harassment.
- Do not evade Telegram limits, FloodWait, bans, reports, or anti-abuse
  controls.
- Do not add users to groups or channels without consent.
- Do not impersonate a person outside the approved ERIS chat context.
- Honor opt-out immediately and do not re-contact marketing opt-outs.
- Pause sending if Telegram returns FloodWait, peer flood, account restriction,
  or repeated user reports.

## Daily Preflight

- Confirm `MTProto_ENABLED` is intended for the environment.
- Confirm production `TELEGRAM_SESSION_STRINGS` is empty.
- Confirm active `telegram_accounts` are authorized and not banned.
- Confirm per-account counters are below signed limits.
- Confirm opt-out and safety queues have no unresolved blocker.

## Pause Conditions

Pause affected accounts or the full pool if:

- FloodWait or peer flood is returned by Telegram.
- Any account status becomes banned, restricted, or disabled.
- User report, block, or opt-out rate rises above normal baseline.
- Outbound failures exceed 5% over the last hour.
- A session, `api_hash`, or Fernet key may have leaked.
- An operator requests pause for safety, privacy, or ToS review.

## Incident Actions

- Disable the affected `account_id`.
- Stop queued outbound tasks for that account.
- Preserve logs after redaction.
- Notify release owner and document the incident.
- Resume only after the root cause is fixed and counters are reset.

## Acceptance Checklist

- [x] Written SOP is signed.
- [x] Frequency limits are signed and machine-readable.
- [x] Batch limits prohibit cold outreach and marketing blasts.
- [x] ToS guardrails are explicit.
- [x] Pause conditions and incident actions are documented.

## Change Control

Any increase to frequency, batch size, cold outreach behavior, or pool
parallelism requires a new signed H-11 policy revision before implementation.
