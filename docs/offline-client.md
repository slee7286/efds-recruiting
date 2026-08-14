# Offline client

When `OFFLINE_MODE=true`, local applications, artifacts, AI task bundles,
conversation search, and review continue using SQLite and the private
filesystem. Shared refresh is skipped. The UI reports offline/cache status and
does not repeatedly attempt network access. Cached public records retain their
sync timestamps and stale-after values.
