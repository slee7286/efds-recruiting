# V9 implementation summary

V9 adds a read-only shared-intelligence API, versioned Pydantic DTOs, bounded
pagination/filtering, manifest/delta sync, tombstone records, HTTP retries and
ETags, and a transport-neutral Postgres/HTTP client boundary. The local
companion adds loopback UI pages for dashboard, jobs, companies, applications,
AI workspace, conversations, local data, settings, and onboarding. It includes
CSRF/host protection, OS secret-store abstraction, API/server CLI commands, a
PyInstaller Windows build spec, and optional Playwright dependency checks.

No private API routes, private telemetry, browser autofill, application
submission, signed installer, or automatic update mechanism is included.
