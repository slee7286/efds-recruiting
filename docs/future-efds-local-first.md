# Future EFDS local-first architecture

```text
EFDS / shared service: public recruiting intelligence
                    │ HTTPS read/sync only
                    ▼
Student local assistant: SQLite, applications, CVs, answers,
AI chats, browser autofill, preparation history
                    │ explicit user-reviewed publish only
                    ▼
Optional sanitized shared contribution
```

EFDS should expose public intelligence endpoints such as `GET /companies`,
`GET /jobs`, `GET /companies/{id}/intelligence`, and `GET /resources`. It should
not expose private-CV, application, answer, AI-history, or browser-state write
endpoints by default. A desktop app, localhost companion, CLI, or browser
extension may be considered later; none is silently trusted with submission.
