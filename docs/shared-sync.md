# Shared synchronization

`recruiting sync pull` uses the shared HTTP API by default and writes only local
cache/state rows. It supports `--company`, `--since`, and `--dry-run`. Remote
wins for cached public objects; local notes are separate and are never
overwritten. Set `SHARED_TRANSPORT=postgres` only for developer/admin direct-DB
mode.

`recruiting sync status` reports object-level freshness. Jobs use a shorter
default freshness window than general intelligence. Distributed clients use
the shared HTTPS API; direct Postgres remains an explicit developer/admin mode.
