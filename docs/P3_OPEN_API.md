# P3 Open API MVP

This document records the first stable App/Web/Open API surface. The API is a
thin client-facing layer over existing ERIS services; it must not replace or
bypass content safety, minor protection, consistency checks, memory writing,
policy handoff, or the LLM orchestrator.

## Namespace

All endpoints live under:

```text
/api/v1/open
```

## MVP Authentication

Until App/Web user JWTs are implemented, the MVP uses `X-User-Id` as a caller
identity guard:

- GET endpoints require `X-User-Id`.
- POST endpoints that include `user_id` reject mismatches when `X-User-Id` is
  provided.
- This is a P3 MVP constraint, not a long-term auth model. A later phase should
  replace it with user JWT/session auth and signed client credentials where
  needed.

## Endpoints

### `GET /api/v1/open/characters`

Returns active characters only. The response intentionally excludes internal
prompt fields and personality score details.

Public fields:

- `id`
- `name`
- `age_feel`
- `region`
- `occupation`
- `background`
- `relationship_position`
- `default_language`
- `supported_languages`
- `tone`
- `reply_length`

### `GET /api/v1/open/users/{user_id}/profile`

Returns a safe App/Web initialization profile:

- user nickname, language, timezone
- `relationship_stage`
- current character id/name
- onboarding step/completion
- safe preferences: `chat_style`, `interests`, `current_intent`

The endpoint does not expose sensitive operational fields such as
`risk_score`, `dependency_score`, `is_minor_suspected`, or safety internals.

### `POST /api/v1/open/conversations`

Creates or reuses an `AI_ACTIVE` conversation for a user and active character.

Rules:

- user must exist and be active
- character must exist and be active
- existing `AI_ACTIVE` conversation for the same user and character is reused
- operator/handoff states are not created by this public endpoint

### `POST /api/v1/open/conversations/{conversation_id}/messages`

Sends a text message and returns the user message plus assistant reply.
Only `content_type="text"` is supported in this MVP.

The endpoint uses the existing production chain:

- minor protection
- inbound content safety
- user message persistence
- Redis short context
- memory writer enqueue
- `generate_reply()` LLM orchestrator
- reply consistency check
- assistant message persistence

If a safety rule blocks the message, the API returns `403` with a client-safe
summary:

```json
{
  "detail": {
    "message_id": "...",
    "conversation_id": "...",
    "safety": {
      "blocked": true,
      "reason": "keyword:pattern_0"
    },
    "trace_id": "..."
  }
}
```

The raw `safety_result`, model name, policy internals, and risk scores are not
returned.

### `GET /api/v1/open/conversations/{conversation_id}/messages`

Lists visible conversation messages with:

- `limit` default `50`, max `100`
- optional `before=<message_id>` cursor
- `has_more` boolean

Returned message fields are limited to `id`, `sender_type`, `content`,
`content_type`, and `created_at`.

## Error Semantics

- `400/422`: malformed or invalid request values
- `403`: caller does not match the requested user/resource, or safety blocks
  message processing
- `404`: user, character, or conversation does not exist
- `409`: user/conversation state conflict
- `502`: LLM upstream/orchestrator unavailable

## Known Limits

- `X-User-Id` is a temporary MVP guard.
- The Open API currently covers the minimal chat loop and public read surfaces;
  billing, API keys, Admin UI, operator quality scoring, and third-party OAuth
  remain outside this task.
