# Supabase/PostgreSQL setup

Create a private Supabase project and use its PostgreSQL connection string in `.env`:

```text
DATABASE_URL=postgresql+psycopg://postgres:<password>@<host>:5432/postgres
```

Supabase may provide `postgresql://` or `postgres://` URLs. The runtime normalizes both to SQLAlchemy's `postgresql+psycopg://` dialect. Do not commit the password or a `.env` file. Prefer Supabase's pooled connection for application traffic and a direct connection for migrations when the project/network setup requires it.

Run:

```bash
quant-recruiting db upgrade
quant-recruiting db check
```

`db check` reports connectivity, PostgreSQL version, Alembic current/head, migration status, installed optional extensions, and a temporary-table read/write check. V2 does not require a PostgreSQL extension beyond the database capabilities already used by the schema.

For tests, set `TEST_DATABASE_URL` to a dedicated PostgreSQL database or a connection with permission to create isolated schemas. The integration fixture creates a random schema and drops only that schema. Never point it at a production database without an approved isolated schema policy.
# V3 notes

Use a Supabase PostgreSQL connection string in `DATABASE_URL` (prefer the
provider's pooled/runtime-appropriate connection string for the deployed
context). Keep `psycopg` in the environment and run `recruiting db upgrade`.
Credentials are never stored in the repository or printed by diagnostics.
