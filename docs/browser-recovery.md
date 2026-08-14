# Browser recovery

A logical browser run records execution attempts and checkpoints locally. A
crash or site change marks the attempt failed; it does not make the run ready.
Use:

```text
recruiting browser status <run-id>
recruiting browser restart <run-id>
recruiting browser resume <run-id>
```

Restarting preserves the failed attempt and starts a new `PRELOGIN` attempt.
Resume always rechecks packet freshness and refuses submitted runs. A changed
approved CV, answer pack, or payload requires a new safe attempt.
