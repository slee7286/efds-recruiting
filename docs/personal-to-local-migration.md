# Personal-to-local migration

Use `recruiting migrate personal-to-local --dry-run` to preview legacy private
rows, then run without `--dry-run` to copy them into SQLite. The migration is
non-destructive: it leaves the original PostgreSQL rows unchanged, preserves
UUIDs, copies referenced files when available, and reports counts.

The legacy server-side private tables remain temporarily for compatibility but
are not the local-first client authority.
