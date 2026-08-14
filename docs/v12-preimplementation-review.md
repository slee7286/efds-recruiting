# V12 pre-implementation review

V11 already establishes the correct local-only boundary for applications, email,
browser runs, artifacts, and preparation history. V12 extends that foundation
additively; it does not move private data into the shared database.

## ROBUST

- Browser runs, field mappings, uploads, validation errors, screenshots, and
  packet references are stored through the local SQLite session.
- The final-submit guard is enforced in the browser engine and manual submission
  is recorded separately from automation.
- Greenhouse, Lever, Ashby, and the conservative generic adapter have fixture
  coverage and exact-value verification.
- V11 email, reminder, timeline, assessment, and preparation records are local.
- Shared synchronization is public-data-only and already has offline fallback.
- Stable UUIDs, packet hashes, and application artifact freshness checks provide
  a useful basis for restart and diagnostic work.

## REAL_WORLD_RISK

- Form inspection currently relies heavily on simple CSS selectors and does not
  consistently record selector strategy, frame identity, accessible names, or
  selector drift.
- A logical browser run has no explicit attempt/checkpoint history, making a
  browser crash or a site change harder to resume safely.
- The generic adapter does not model provider capability levels and can expose
  more apparent coverage than has actually been tested.
- Diagnostics currently cover local browser dependency health, but not a
  sanitized DOM, adapter evidence, console/network summary, or export bundle.
- Background work has no single-run orchestration, overlap lock, run history, or
  Windows Task Scheduler contract.
- Gmail remains a provider abstraction rather than a completed live OAuth flow.
- No real packaged Windows build has been verified in this environment.

## ATS_SPECIFIC_GAP

- Workday, SmartRecruiters, iCIMS, Workable, BambooHR, SuccessFactors, and Taleo
  are not represented by an explicit capability registry or detection layer.
- Workday résumé-parser mismatches and repeatable education/experience sections
  have no first-class local record.
- iframe-aware inspection, accessible combobox handling, and provider-specific
  selector diagnostics need additive support.

## RESUME_RISK

- `resume_browser` re-enters the existing logical run without a persisted
  execution-attempt model.
- The current run status does not distinguish a safe logical checkpoint from a
  browser process that has died.
- There is no explicit restart operation that preserves failed attempts while
  starting a clean execution attempt.

## BACKGROUND_TASK_GAP

- Email sync, public sync, reminder evaluation, active-job freshness, and job
  alerts are not coordinated by a local `run-once` runner.
- There is no local lock or structured background-run history.
- Task Scheduler installation/status/removal is not yet implemented.

## PRIVACY_RISK

- Any new diagnostic or fixture-capture path must sanitize values, hidden token
  fields, and browser session material before exporting.
- Provider-specific browser profiles and Gmail OAuth tokens must remain in local
  secret/profile storage and outside backups, telemetry, and shared sync.
- Browser metrics and job-alert rules must remain local; they must not become
  shared API payloads.

## TEST_COVERAGE_GAP

- Existing tests cover Greenhouse and a fake ATS no-submit workflow, but not
  capability reporting for the broader ATS set.
- There are no regression fixtures for Workday parser mismatches, SmartRecruiters
  or iCIMS detection, accessible frames/comboboxes, selector drift, or crash
  restart behavior.
- Background overlap locking, task XML generation, job alerts, diagnostic
  sanitization, and privacy scanning require fixture-based tests.

## V12 implementation boundary

V12 will add a capability registry, conservative provider detection/adapters,
local browser attempts/checkpoints, sanitized diagnostics and fixture capture,
and a local background runner with Task Scheduler contracts. Workday and iCIMS
will not be described as fully supported unless fixture-backed behavior proves
that claim. Final submission, CAPTCHA solving, credential automation, and any
private shared write remain prohibited.
