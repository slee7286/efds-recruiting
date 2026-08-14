# Reminders and notifications

Reminders and notifications are local SQLite records. Due reminders can be delivered to
the local dashboard; desktop notification integration is intentionally conservative and
has a dashboard fallback.

```bash
recruiting notifications list
recruiting notifications list --deliver
```

The local process must run for dashboard delivery. Windows scheduled-task integration is
an optional future packaging enhancement.
