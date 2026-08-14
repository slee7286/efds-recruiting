# Local storage

The default private directory is `%LOCALAPPDATA%/RecruitingAssistant` on
Windows and `~/.recruiting-assistant` elsewhere. `LOCAL_DATA_DIR` and
`LOCAL_DATABASE_URL` override it.

The directory contains `recruiting.db`, `profile/`, `applications/`,
`conversations/`, `research-cache/`, `exports/`, `browser-profiles/`, `logs/`,
and `cache/`. SQLite enables foreign keys, WAL mode, busy timeout, integrity
checks, and FTS5 where available.

## Local schema strategy

The shared PostgreSQL Alembic history is not pointed at the local database.
`local_db.py` owns a curated local table set and records its schema version in
`local_schema_version`. Local upgrades are additive and version-checked; a
future incompatible change must add an explicit local schema migration rather
than silently recreating or dropping the private database. The local schema
uses stable UUIDs for references to synchronized shared objects.
