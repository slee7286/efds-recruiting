# V8 local-first architecture audit

## Current-state findings

The repository is a PostgreSQL/Alembic-first modular monolith. The existing
models combine public recruiting intelligence and private candidate/application
records in one metadata graph. Filesystem artifacts are already versioned and
the CLI currently obtains its sessions from the single PostgreSQL URL in
`Settings`. The V6 review workspace and artifact services therefore need a
storage-routing boundary before they can be used safely in a local-first
client.

The existing PostgreSQL migration chain is retained as the shared/legacy
chain. It is not pointed at SQLite because its PostgreSQL-specific types,
extensions, constraints, and complete historical schema are not a safe local
client contract.

## Ownership classification

| Classification | Existing entities | V8 treatment |
| --- | --- | --- |
| `SHARED_PUBLIC` | companies, aliases, domains, jobs, job observations, ATS metadata, research sources/documents/claims, recruiting cycles/events, interview reports/questions, skills, resources, public firm intelligence | remain on shared PostgreSQL; cache locally by stable UUID |
| `LOCAL_PRIVATE` | candidate profile, sensitive fields, experiences, evidence, stories, CV versions/bullets, applications, application events, requirements, gaps, arguments, questions/answers, artifacts, review events, question attempts | local SQLite is the new canonical client store |
| `MIXED_NEEDS_SPLIT` | candidate-firm matches, AI tasks/runs/outputs, application-to-company/job joins, resource annotations, research notes | private portions move local; public references use shared UUIDs/cache rows |
| `INFRASTRUCTURE` | Alembic, settings, filesystem paths, HTTP/discovery code, templates, CLI, review server, provider contracts | route explicitly to local or shared services |
| `DEPRECATED_FOR_CLIENT_USE` | direct shared-Postgres writes for private application workflows; server-side private tables as a client default | retain temporarily for migration/backward compatibility, never use in `local_first` mode |

## Boundary decisions

1. PostgreSQL/Supabase remains a shared intelligence store and development/admin
   source. It is not the default personal application database.
2. SQLite is the canonical local store for private data, AI task history,
   artifacts, review state, browser audit state, and local notes.
3. Local shared-cache rows contain stable remote IDs, versions, timestamps, and
   hashes, but no remote foreign keys and no private uploads.
4. Automated synchronization is one-way: shared → local. Any future local →
   shared operation is an explicit publishing workflow with preview,
   sanitization, destination, and audit records.
5. AI conversation text is local context, never authoritative source or
   candidate evidence. Claims still require research provenance and candidate
   facts still require approved local evidence.

## V8 implementation shape

- `local_db.py` owns the SQLite engine, WAL/foreign-key setup, and local
  migration bootstrap.
- `local_models.py` contains the private schema and compact shared-cache rows.
- `storage.py` exposes explicit local/shared session and repository boundaries.
- `sync.py` uses shared snapshots and writes only cache tables locally.
- `ai_workspace.py` owns provider-neutral launch and local conversation import,
  archive, and FTS retrieval.
- Existing artifact/review services gain local-first routing without deleting
  the existing PostgreSQL models or migration history.

## Deliberate non-goals

V8 does not implement hosted private-data APIs, background private uploads,
browser autofill, final application submission, provider DOM automation, custom
cryptography, or anonymous contribution analytics. The existing shared
PostgreSQL workflow remains available as a transitional developer/admin mode.
