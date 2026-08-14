# Local background runner

`recruiting background run-once` performs bounded local operations: public
shared sync when configured, reminder evaluation, local job-alert matching, and
freshness checks for active local applications. It never opens a browser, sends
email, or opens an AI provider. Gmail is recorded as skipped until a local
OAuth provider is explicitly configured.

A filesystem lock prevents overlap. Runs and task results are stored in local
SQLite only. The runner can be invoked by Windows Task Scheduler through
`recruiting background install`, `status`, and `remove`; task XML generation is
tested without modifying a real scheduler.
