# ERIS Database Schema Document

Status: P1-01 accepted baseline.

This document records the Phase 01 data structures that are required before
the Telegram real-user inbound path, premium chat traceability, and audit query
surface can be considered complete.

## user_profiles

Source: `db/migration/V1__init.sql`

Purpose: stores user profile attributes used by the level engine, discovery
flows, and AI routing.

Key columns:

| Column | Type | Notes |
| --- | --- | --- |
| id | UUID | Primary key |
| user_id | UUID | Unique FK to `users.id` |
| age | INTEGER | Optional user age |
| country | VARCHAR(10) | ISO-like country code |
| gender | VARCHAR(20) | Optional profile value |
| language | VARCHAR(10) | Defaults to `en` |
| tags | TEXT[] | Search/routing tags |
| preferences | JSONB | Flexible profile preferences |

## premium_chat_logs

Source: `db/migration/V8__p1_premium_chat_and_audit_logs.sql`

Purpose: records premium S/A chat events with enough context to trace platform,
account routing, script hits, and message direction without reading raw provider
payloads from operational logs.

Key columns:

| Column | Type | Notes |
| --- | --- | --- |
| id | UUID | Primary key |
| user_id | UUID | Optional FK to `users.id` |
| external_user_id | VARCHAR(128) | Provider-stable user key before DB binding |
| conversation_id | UUID | Optional FK to `conversations.id` |
| message_id | UUID | Optional FK to `messages.id` |
| platform | VARCHAR(40) | Defaults to `telegram_real_user` |
| account_id | VARCHAR(64) | AccountPool account used for routing |
| sender_phone | VARCHAR(32) | Nullable; responses must redact |
| direction | VARCHAR(20) | `inbound` or `outbound` |
| message_type | VARCHAR(20) | Text/photo/voice/etc. |
| script_hit_id | VARCHAR(128) | Matched script id when available |
| payload | JSONB | Small structured context |
| created_at | TIMESTAMP | Audit timestamp |

Indexes cover user, external user, conversation, and `script_hit_id` lookup.

## audit_logs

Source: `db/migration/V8__p1_premium_chat_and_audit_logs.sql`

Purpose: append-only operational audit trail. P1-16 requires the latest 100
entries to be queryable, and P1-06 writes an `inbound_queue.consumed` record
when a Redis Stream message is processed successfully.

Key columns:

| Column | Type | Notes |
| --- | --- | --- |
| id | UUID | Primary key |
| trace_id | VARCHAR(64) | Request or queue trace id |
| event_type | VARCHAR(80) | Example: `inbound_queue.consumed` |
| source | VARCHAR(80) | Producer or service name |
| actor_type | VARCHAR(40) | `system`, `operator`, or integration |
| actor_id | VARCHAR(128) | Optional actor id |
| user_id | VARCHAR(128) | External or canonical user key |
| conversation_id | UUID | Optional conversation id |
| message_id | UUID | Optional message id |
| platform | VARCHAR(40) | Source platform |
| account_id | VARCHAR(64) | Telegram account route |
| sender_phone | VARCHAR(32) | Stored only when required; API redacts |
| script_hit_id | VARCHAR(128) | Matched script id when available |
| payload | JSONB | Structured details |
| created_at | TIMESTAMP | Descending query index |

Indexes cover recent queries, user lookup, trace lookup, and event type lookup.

## Acceptance Mapping

| Task | Acceptance | Evidence |
| --- | --- | --- |
| P1-01 | `db_schema_doc.md` passes | This document plus V8 migration |
| P1-06 | Queue smoke passes | `services.inbound.queue_consumer` + tests |
| P1-16 | Recent 100 audit rows queryable | `services.audit_log_service` + `/api/v1/audit-logs/recent` |
