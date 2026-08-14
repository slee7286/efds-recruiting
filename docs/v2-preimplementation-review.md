# V2 pre-implementation review

## Scope inspected

I inspected the V1 package, all SQLAlchemy model declarations, the initial Alembic revision, configuration/session handling, web normalization/persistence, CLI, tests, documentation, and the repository filesystem conventions.

## What is sound and will be preserved

- PostgreSQL is the declared canonical database and the SQLAlchemy metadata already contains the complete V1 domain model.
- Source rows have a logical canonical URL, retrieval timestamp, raw hash, quality, and filesystem paths.
- Normalized research documents are versioned by source and retain prior content.
- The CLI is grouped by domain and the AI queue is a deliberate handoff boundary rather than an LLM runtime.
- Raw and normalized artifacts are separated under configurable local directories.
- V1 tests already cover model shape, URL hashing, normalization, frontmatter, and a PostgreSQL-gated workflow.

## Concrete risks and technical debt relevant to V2

1. The initial migration uses `Base.metadata.create_all()` rather than explicit Alembic operations. It is acceptable for a fresh V1 database, but future migrations must use stable explicit operations so later model changes cannot mutate historical revisions.
2. `db check` only executes `SELECT 1`; it does not report PostgreSQL/Alembic state, extension availability, or a safe write check.
3. The settings loader supports `DATABASE_URL` but not a first-class `TEST_DATABASE_URL` setting. Integration tests construct their own engine, which is safe but does not exercise the application session factory.
4. There is no company-domain table, deterministic company resolver, discovered-URL persistence, source discovery provenance, or incremental discovery state.
5. Jobs have uniqueness indexes for company/URL and company/external ID, but no observation/history model. This cannot represent description/deadline changes or close/reopen transitions with provenance.
6. Web fetching has no retry policy, maximum response size, content-type validation, per-host delay, structured fetch-error persistence, or configurable timeout.
7. The current collector is both the only discovery shape and the fetch/normalize implementation. V2 needs an explicit discovery-provider boundary while retaining the collector for ingestion.
8. URL canonicalization removes UTM parameters and sorts query pairs, but it should be centralized and tested more comprehensively before discovery depends on it.
9. The V1 source persistence path can encounter a normalized-content uniqueness conflict if raw HTML changes without changing normalized text. V2 will make source-version identity explicit and preserve raw and normalized observations safely.
10. The current research export is a flat source index. V2 can extend it into deterministic firm/recruiting sections without generating unsupported prose.
11. Logging and verbosity controls are not yet present. They are required before network discovery is used against real domains.

## V2 safety decisions

- Additive schema changes will use a new explicit Alembic migration.
- Discovery will persist candidate URLs before ingestion and will never silently fetch an entire domain.
- Robots rules, allowed domains, depth/page limits, response limits, and polite host delays will be enforced by the website provider/fetcher.
- Job identity will prefer external identifier, then canonical URL, with deterministic fallback only when necessary; observations will retain changes.
- Company resolution will use exact deterministic rules and raise on ambiguity.
- No credentials, authenticated scraping, search-engine discovery, LLM calls, browser automation, application submission, social scraping, or EFDS integration will be added.
- Live Supabase verification will only be claimed when a real `DATABASE_URL` is supplied and used.
