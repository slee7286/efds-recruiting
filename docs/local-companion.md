# Local companion

`recruiting app serve` runs the Recruiting Assistant on loopback. It uses local
SQLite and local files for applications, profile data, AI tasks, conversations,
artifacts, and review. It displays cached public jobs and companies without
requiring the shared service to be reachable. `recruiting app open` opens an
already-running instance.

The UI is deliberately server-rendered and small. Application pages expose an
explicit Browser Autofill section with local run history, status, unresolved
fields, and review/checklist paths. A run requires a verified local packet and
always stops before final submission.
