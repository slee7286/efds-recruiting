# Local-first architecture

The shared PostgreSQL/Supabase service stores public recruiting intelligence.
The local SQLite database stores the candidate's private recruiting workspace.

```text
shared PostgreSQL / API
public companies, jobs, research, resources
              │ one-way pull
              ▼
local SQLite + private filesystem
applications, CVs, answers, AI history, review, browser audit
              │ explicit user handoff
              ▼
ChatGPT / Claude / Gemini / custom provider
```

Shared reads are optional after synchronization. Private writes use
`private_session_scope()` and local paths in `LOCAL_DATA_DIR`. No private
write path calls the shared session automatically.

V11 email, application outcomes, assessment/interview details, timelines, reminders,
contacts, notes, notifications, and preparation history are local operational data.
Only public job freshness may be pulled from the shared service.
