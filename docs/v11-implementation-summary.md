# V11 implementation summary

V11 adds local-only recruiting email ingestion, deterministic classification and
application linking, email-provenanced status events, assessment/interview extraction,
timezone-aware deadline handling, timeline/actions/reminders, ICS export, deterministic
preparation-plan drafts, local operational UI pages, and job freshness checks before
Playwright preflight.

Gmail is represented by an OAuth/provider abstraction and was not live-authorized in the
development environment. EML fixtures are the deterministic verification path. Email,
outcomes, appointments, reminders, notes, contacts, and preparation records do not exist
in the shared API contract.
