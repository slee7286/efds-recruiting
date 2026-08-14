# Quant Recruiting Intelligence System V1 — Implementation Plan

## Package structure

Use a `src/quant_recruiting` package split into configuration, database models/session, domain services, ingestion, exports, and CLI modules. Keep raw and normalized artifacts under configurable local data directories, with research exports separate from source storage. Keep this repository and database independent from the EFDS website.

## Model organization

Use one SQLAlchemy declarative base with modular model files grouped by domain: companies/jobs, applications, provenance/research, recruiting/interviews, skills/resources, candidate evidence, writing, preparation, and AI tasks. Use PostgreSQL-native UUIDs, JSONB, timestamps, foreign keys, check constraints, indexes, and explicit association tables. Flexible values use string columns with documented initial values so new values remain ingestible.

## Migration strategy

Use Alembic with `migrations/` as the migration script location and an importable `Base.metadata` target. The initial migration creates every V1 table, enum-like check constraints, indexes, and uniqueness rules. Runtime services use SQLAlchemy 2.x sessions and work against local PostgreSQL or hosted Supabase Postgres through `DATABASE_URL`; SQLite is not a supported primary backend.

## CLI structure

Expose a Typer application as `quant-recruiting`. Commands are grouped by `db`, `company`, `job`, `source`, `research`, `ai`, and `seed`. Commands call small service functions rather than embedding persistence logic. Database commands run migrations/checks, source commands perform deterministic URL ingestion, research commands render YAML-frontmatter Markdown, and AI commands produce a human/interactive-session task package without invoking an LLM.

## Filesystem strategy

Use `.env`-driven `DATA_DIR`, `RESEARCH_DIR`, and `HTTP_USER_AGENT` with safe local defaults. Raw HTML is saved in `data/raw/<company>/<source-id>/` using content-addressed/versioned filenames; normalized Markdown is saved in `data/normalized/<company>/<source-id>/`. Research exports live in `research/<company>/`, AI task packages in `data/ai_queue/<task-id>/`, and transient cache data in `data/cache/`. Historical artifacts are retained rather than silently overwritten.

## Testing strategy

Use pytest with a PostgreSQL test database when `TEST_DATABASE_URL` is configured, plus focused pure-service tests that run without a database. Cover constraints, URL canonicalization, content hashes, idempotent ingestion/versioning, exporter frontmatter, AI manifests, idempotent skill/company seeding, application event history, and model relationships. Verification includes Ruff, mypy where practical, pytest, Alembic upgrade/current checks, CLI loading, and an end-to-end local HTML fixture workflow.
