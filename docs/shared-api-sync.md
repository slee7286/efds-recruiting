# Shared API sync

The local client requests a versioned manifest and then `/sync/changes` with a
timestamp cursor. DTOs are validated before a local transaction applies them.
Remote changes are represented as upserts or tombstones; clients do not infer
deletions from absence. HTTP retries are bounded and 5xx/timeouts are retried
with backoff. ETags support a cheap unchanged-manifest check.

`SHARED_TRANSPORT=postgres` remains a developer/admin compatibility mode. New
installations default to `api`; the client does not need PostgreSQL or Supabase
credentials.
