# Browser run lifecycle

```text
preflight → launch → inspect → map → fill → verify → final review
                                      ↘ needs_input / failed
```

Runs are local SQLite records with local JSON, screenshots, validation errors,
and review files. Packet version and approved artifact hashes are captured at
run creation. Each logical run now records execution attempts and checkpoints;
`browser restart` starts a new attempt without overwriting failure history.
Resume refuses stale packet versions. A run observed as submitted becomes
read-only.
