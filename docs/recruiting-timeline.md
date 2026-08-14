# Recruiting timeline

Local `timeline_events` combine application, email, assessment, interview, deadline, and
manual events. Every email-derived event retains the source message ID and extraction
metadata. Timeline timestamps are timezone-aware where the message provides enough
information; ambiguous times are marked `needs_review`.

```bash
recruiting timeline show
recruiting timeline show --upcoming
```
