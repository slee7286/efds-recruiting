# Local Gmail OAuth

V11/V12 keep Gmail behind `RecruitingEmailProvider`. The intended production
flow uses Google's official OAuth authorization with the minimum read-only
scope:

```text
https://www.googleapis.com/auth/gmail.readonly
```

No password, send, delete, archive, or modify scope is requested by the
application layer. OAuth tokens belong in the local OS-backed `SecretStore`,
never in SQLite rows, shared Postgres, logs, or task bundles. This repository
contains the provider boundary and read-only scope contract; live Google OAuth
client wiring is deployment-specific and was not claimed as verified here.
