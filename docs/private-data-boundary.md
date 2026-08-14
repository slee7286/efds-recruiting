# Private-data boundary

The local data directory is private. It may contain names, contact details,
CVs, answers, sensitive fields, screenshots, browser profiles, and AI chats.
These are not telemetry and are never automatically uploaded.

`auto_push_private` is hard-disabled in configuration. The only future
local-to-shared path is an explicit publish intent with preview, field-level
sanitization, destination, consent, and audit history.

Browser autofill is also local-only. Browser runs, form snapshots, field
mappings, uploads, screenshots, sensitive values, and submission observations
are private records. The shared API has no browser or application routes.

Recruiting email, outcomes, assessment links/deadlines, interview appointments,
timeline/actions, reminders, contacts, notes, notifications, and preparation plans
are likewise local-only and are never automatically published.
