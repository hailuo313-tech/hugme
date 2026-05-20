# P1-02 Flyway Initial Migration

Status: implemented  
Task: P1-02 - 编写 Flyway V1__init.sql  
Acceptance: empty database can migrate from the initial schema

## Migration

The Flyway baseline migration is:

- `db/migration/V1__init.sql`

It mirrors the existing Docker bootstrap schema in:

- `scripts/init.sql`

Keeping both files identical lets fresh local Docker volumes and Flyway-managed
environments start from the same schema contract.

## Empty-Database Verification

Run against an empty PostgreSQL database that has the pgvector extension
available, such as the repository's `pgvector/pgvector:pg16` image:

```bash
flyway \
  -url="jdbc:postgresql://127.0.0.1:5432/eris" \
  -user="$POSTGRES_USER" \
  -password="$POSTGRES_PASSWORD" \
  -locations="filesystem:db/migration" \
  migrate
```

Expected result:

- Flyway applies `V1__init.sql`.
- Core extensions are created: `uuid-ossp`, `vector`, `pg_trgm`.
- Core tables exist: `users`, `user_profiles`, `conversations`, `messages`,
  `memories`, `handoff_tasks`, `orders`, `operators`, and
  `stripe_webhook_events`.

## Local Guard

The repository includes a lightweight guard:

```bash
python -m pytest tests/test_p1_02_flyway_init.py -q
```

The test verifies the Flyway filename, required extension/table statements, and
that `db/migration/V1__init.sql` stays byte-for-byte aligned with
`scripts/init.sql`.
