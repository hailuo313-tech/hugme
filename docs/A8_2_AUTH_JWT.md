# A8-2 Auth / JWT Contract

This document signs off the current MVP authentication contract as implemented
on `main`. It is a documentation and operations baseline, not a new auth
feature.

## 1. Overview

The MVP only has Operator JWT authentication for admin and operator workflows.
Telegram users and future app users do not have `scope=user` tokens yet.

User-scoped tokens, refresh tokens, Telegram `initData` verification, and
device/session management are Phase 2 work and must not be described as
production behavior until code lands.

## 2. Issuer

- Issuer: ERIS FastAPI.
- Signing key: `SECRET_KEY`, loaded by `Settings` and passed into the API
  container through `docker-compose.yml` `api.environment`.
- Algorithm: HS256.
- Implementation: [app/api/admin.py](../app/api/admin.py), pure stdlib HMAC
  JWT helpers.

`SECRET_KEY` must stay in the runtime `.env` or secret store. Do not commit a
real production key.

## 3. Login Flow

Endpoint:

```http
POST /api/v1/admin/login
Content-Type: application/json

{"username":"admin","password":"..."}
```

The API checks the `operators` table for:

- `username`
- `password_hash`
- `status = 'active'`

Passwords are currently stored as SHA256 hex via `_hash_password()` in
`app/api/admin.py`. This is accepted for the MVP baseline but is technical debt;
a later auth hardening task should migrate operator passwords to bcrypt or
Argon2 with per-password salts.

## 4. Claims

Operator tokens contain:

| Claim | Meaning |
| --- | --- |
| `sub` | operator id |
| `username` | operator username |
| `role` | operator role from the `operators` table |
| `type` | fixed value `operator` |
| `iat` | issued-at Unix timestamp |
| `exp` | expiry Unix timestamp |

There is no `scope=user` claim in the MVP.

## 5. Lifetime

Default lifetime is 7 days:

```text
expires_in = 86400 * 7
```

There is no refresh token. When a token expires, protected API calls return
`401`; the Admin frontend clears local auth state and sends the operator back
to `/admin/login`.

## 6. Verification

Protected endpoints expect:

```http
Authorization: Bearer <operator-jwt>
```

`require_operator()` verifies the HS256 signature using `SECRET_KEY`, rejects
expired tokens, and requires `type == "operator"`. Missing, invalid, expired, or
wrong-type tokens return `401`.

## 7. Protected Surface

| Surface | Current auth behavior | Notes |
| --- | --- | --- |
| `POST /api/v1/admin/login` | Public | Login endpoint; returns operator JWT on valid credentials. |
| `GET /api/v1/admin/me` | Requires operator JWT | Calls `require_operator`. |
| `GET /api/v1/admin/conversations` | Requires operator JWT | Calls `require_operator`. |
| `GET /api/v1/admin/conversations/{conversation_id}` | Requires operator JWT | Calls `require_operator`. |
| `POST /api/v1/admin/silent-reactivation/run` | Requires operator JWT | Calls `require_operator`; feature behavior still depends on `SILENT_REACTIVATION_ENABLED`. |
| `POST /api/v1/users/{user_id}/memories/retrieve` | Not protected on current `main` | Current code does not call `require_operator`; CUR-API-01 should add operator JWT before treating it as private admin data. |
| Other `app/api/memories.py` routes | Not protected on current `main` | Must be treated as pending auth hardening if exposed outside trusted paths. |
| `app/api/handoff.py` routes | Not protected on current `main` | Operator auth should be added before public exposure. |
| `app/api/notifications.py` operator-style list/cancel/log routes | Not protected on current `main` | Keep behind trusted network or harden in a follow-up. |

## 8. Admin Frontend

Frontend auth helpers live in [admin/lib/auth.ts](../admin/lib/auth.ts):

- `TOKEN_KEY = "eris_admin_token"`
- `OPERATOR_KEY = "eris_admin_operator"`
- `LOGIN_PATH = "/admin/login"`
- `API_BASE = "/api/v1"`

`apiFetch()` sends `Authorization: Bearer <token>` when present. On `401`, it
clears local storage and redirects to `LOGIN_PATH`.

## 9. Key Rotation

Changing `SECRET_KEY` invalidates every existing operator token.

Recommended rotation:

1. Verify staging with the new `SECRET_KEY`.
2. Update production runtime `.env` or secret store; do not commit the value.
3. Recreate the API container:

   ```bash
   cd /opt/eris
   docker compose up -d api
   ```

4. Ask operators to log in again.
5. Confirm `GET /api/v1/admin/me` returns `200` with a fresh token and `401`
   with an old token.

## 10. Future Extensions

Planned but not implemented:

- `scope=user` / app-user JWTs.
- Refresh tokens and token revocation.
- Telegram WebApp `initData` verification.
- Password hashing migration from SHA256 hex to bcrypt or Argon2.
- Operator JWT enforcement for memories, handoff, and notification operator
  surfaces.

Keep these as design placeholders until Rev-C or a dedicated Cursor task lands
the code and tests.

## 11. Acceptance Commands

Run on the server from `/opt/eris`. Do not print real passwords or tokens in
chat logs.

```bash
# Health baseline.
curl -fsS http://127.0.0.1:8000/health/detail

# Login. Replace YOUR_PASSWORD locally; do not commit or paste it.
TOKEN=$(curl -fsS -X POST http://127.0.0.1:8000/api/v1/admin/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"YOUR_PASSWORD"}' \
  | docker exec -i eris-api python -c "import sys,json; print(json.load(sys.stdin)['token'])")

# Protected success path.
curl -fsS -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/v1/admin/conversations?page=1&page_size=5" \
  | docker exec -i eris-api python -m json.tool

# Protected failure path: must be 401.
curl -fsS -o /dev/null -w "admin-no-token:%{http_code}\n" \
  http://127.0.0.1:8000/api/v1/admin/conversations
```

Expected:

- `/health/detail` returns `api`, `db`, and `redis` as `ok`.
- Admin login returns a JWT.
- Authenticated admin read returns JSON.
- Unauthenticated admin read returns `401`, not `200`.
