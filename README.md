# ERIS

ERIS is the MVP emotional companion platform. Operational notes live in
`RUNBOOK.md`; task-specific designs live in the root `D*-*.md` files.

## D7-3 End-to-End Script

Run the full D7-3 smoke path from the repository root:

```bash
bash scripts/e2e/run.sh
```

The script drives the system with Telegram-shaped webhook updates, so it does
not require a real person using the Telegram mobile app. It covers:

1. Telegram registration through `POST /telegram/webhook`
2. Onboarding steps 1-5
3. 50 normal conversation turns
4. Keyword-triggered operator handoff
5. Handoff lock, reply, and return-to-AI APIs
6. Stripe Checkout order creation

Each major step also verifies DB state and `GET /health/detail`.

Useful environment overrides:

```bash
API_BASE=http://127.0.0.1:8000 \
DB_CONTAINER=eris-postgres \
DB_USER=eris \
DB_NAME=eris \
bash scripts/e2e/run.sh
```

If `psql` is available directly, set `PSQL_DSN` instead:

```bash
PSQL_DSN='postgresql://eris:eris_secret_2026@127.0.0.1:5432/eris' \
bash scripts/e2e/run.sh
```

On the production server:

```bash
cd /opt/eris
API_BASE=http://127.0.0.1:8000 bash scripts/e2e/run.sh
```

How to read results:

- Full pass exits with `0` and prints `RESULT=PASS`.
- Any failed assertion exits with `1` and prints `RESULT=FAIL`.
- The summary shows each `PASS`/`FAIL`, plus the generated `trace_id` values,
  `user_id`, `conversation_id`, `handoff_task_id`, and `order_id`.
- Stripe payment is validated up to Checkout Session creation and DB order
  creation. To manually complete the hosted Checkout page with card `4242 4242
  4242 4242`, run with `STRIPE_TEST_MODE=manual_4242` and open the printed
  `checkout_url`.
