# Local email ingestion

Recruiting email is a local operational input. It is stored in SQLite and local files,
never in the shared PostgreSQL database or shared API.

V11 supports deterministic `.eml` import and a provider-neutral `RecruitingEmailProvider`
protocol. Gmail is represented by an injected OAuth-authenticated API adapter; it does
not scrape Gmail or accept a Gmail password. OAuth wiring remains local-secret-store
work for a deployment environment with credentials.

```bash
recruiting email connect gmail
recruiting email import message.eml
recruiting email status
recruiting email unlinked
```

Retention is configurable through `EMAIL_STORAGE_MODE`:

- `metadata_only`: headers/classification only
- `text_and_metadata`: headers and normalized text, the default
- `raw`: normalized text plus immutable raw EML under the local data directory

Attachments are metadata-only until an explicit future local download workflow is used.
