# Windows Task Scheduler

V12 provides an optional least-privilege Task Scheduler entry named
`RecruitingAssistantBackground`. It invokes `recruiting background run-once`
at a bounded cadence and uses `IgnoreNew` to prevent overlapping runs.

Install/remove it explicitly:

```text
recruiting background install
recruiting background status
recruiting background remove
```

The app does not require administrator permissions where Windows policy allows
an interactive-user task. Test generation is cross-platform; actual install is
Windows-only and must be verified on the user's machine.
