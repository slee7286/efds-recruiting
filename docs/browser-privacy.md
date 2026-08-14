# Browser privacy

Browser runs are local-only. Payloads, CVs, answers, field snapshots,
screenshots, sensitive values, and fill logs are stored below the private local
data directory. The shared API may be used for an explicitly requested public
job-status refresh, but browser content is never sent there. Browser profiles
contain session secrets and are excluded from backups by default.
