# V11 pre-implementation review

## Scope

V10 already has a local-first SQLite store, shared read-only intelligence cache/API,
local applications and artifacts, Playwright runs, deterministic preparation reports,
and a localhost companion. V11 extends only the local operational side of that
architecture.

## Reuse

- `get_local_session()` and the local SQLite bootstrap are the mandatory persistence
  path for email, outcomes, timeline, reminders, and preparation operations.
- `ApplicationEvent` remains the immutable application-status history mechanism.
- Existing companies, jobs, applications, interview questions, skills, resources, and
  question-attempt records are reused as context rather than copied to a hosted store.
- Existing `application_service`, shared-cache freshness fields, and companion CSRF
  handling are reused.
- Existing stable UUIDs and JSON metadata remain suitable for local operational records.

## Extend

- Add local email accounts, threads, messages, attachments, links, and extraction rows.
- Add deterministic classification/linking and provenance spans for every extraction.
- Add local recruiting timeline events, actions, reminders, assessments, appointments,
  contacts, notes, notifications, and preparation plans.
- Add manual EML import and a Gmail provider boundary; OAuth/token handling remains
  behind the local secret-store abstraction.
- Add job freshness checking to browser preflight without sending application data to
  the shared service.

## Missing

- A provider-neutral recruiting-email protocol and local message deduplication.
- Conservative timezone-aware date/deadline extraction.
- Local notification delivery and ICS export.
- Timeline/preparation UI and CLI surfaces.

## Privacy risk

Email bodies, links, recruiter identities, assessment URLs, interview details, outcomes,
notes, reminders, and preparation history are private operational data. They must not
be added to shared models, shared API DTOs, telemetry, or automatic sync paths. AI
conversation context and email context remain separate trust categories.

## Time-sensitive behavior

Assessment deadlines, interview appointments, job closure, and stale job deadlines need
explicit timezone-aware handling. Ambiguous dates remain `needs_review`; low-confidence
email classification must not mutate application status.

## Deliberate V11 boundaries

- Gmail authorization is a legitimate OAuth extension point; fixture/manual import is
  the reliable test path when credentials are unavailable.
- No email sending, calendar write, assessment launch automation, recruiter reply,
  automatic interview booking, or final application submission is implemented.
- Shared API routes remain public-intelligence-only.
