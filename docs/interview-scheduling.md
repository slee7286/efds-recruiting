# Interview scheduling

Explicit date/time invitations can create local interview appointments. Timezone
abbreviations are resolved with `zoneinfo`; a missing timezone remains `needs_review`.
Scheduling links are stored but no slot is selected automatically.

```bash
recruiting interview list
recruiting calendar export <interview-id>
```

ICS output is local and provider-neutral. Direct Google/Outlook calendar writes are not
implemented and would require explicit user action in a later version.
