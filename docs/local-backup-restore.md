# Local backup and restore

`recruiting local backup` creates a private ZIP containing SQLite, profile,
applications, artifacts, conversations, and a hash manifest. Browser profiles
and screenshots are excluded by default; use `--include-browser-state` only
when necessary.

`recruiting local restore <backup> --destination <directory>` validates the
manifest and every file hash before completing. Restore never overwrites an
existing destination.
