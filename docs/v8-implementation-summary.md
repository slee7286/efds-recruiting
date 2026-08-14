# V8 implementation summary

V8 adds a local-first storage boundary while retaining the shared PostgreSQL
intelligence path. Local SQLite uses portable SQLAlchemy UUID/JSON types,
foreign keys, WAL, integrity checks, and FTS5. Local cache/state records stable
shared IDs, hashes, timestamps, and stale status. Shared pulls are one-way.

Private application commands, AI task operations, artifacts, and review now
route through the local session in `local_first` mode. Provider-neutral AI
opening and local ChatGPT/Claude/Gemini/generic conversation import/search are
implemented without API keys or website automation. Backup, restore, export,
cleanup, doctor, and non-destructive personal migration commands are included.

V8 intentionally does not implement a hosted private-data API, automatic
private publishing, browser autofill, final submission, custom encryption,
telemetry, or anonymous contribution analytics.
