# Architecture

The system is a local-first modular application. SQLite is the canonical store
for personal candidate/application state, while PostgreSQL/Supabase stores the
shared public-intelligence corpus. The local client reads shared data through a
versioned API and never needs shared database credentials. The CLI calls domain
services; services persist through SQLAlchemy; separate migration chains own
the local and shared schemas. Filesystem artifacts are evidence and derived
exports, not replacements for database records.

The main flow is:

```text
public source -> raw artifact -> normalized document -> typed claim -> research/export
company domain -> discovery candidate -> bounded ingestion -> source/document/job observation
candidate evidence -> reviewed writing records -> application/CV/answer history
job -> application -> immutable application events -> preparation intelligence
```

Collectors implement a small discover/fetch/normalize shape. V1 supplies only a generic public web collector. Future collectors must respect robots.txt, authentication boundaries, rate limits, and source-specific terms.

V2 makes discovery a separate provider boundary. Discovery persists candidate URLs and reasons before ingestion. The official-site provider reads permitted robots/sitemaps, bounded internal links, and public JSON-LD; ingestion then persists source versions or job observations.

The AI queue is an interface boundary, not an AI runtime. It produces local manifests and instructions for a human or interactive AI session. No API key, ChatGPT browser control, automatic submission, or unsupported synthesis is part of V1.
# V3 generalization

The product is a general Recruiting Intelligence System. Quantitative roles
remain seeded data, not an architectural boundary. Discovery, fetching,
normalization, extraction, and synthesis are separate layers. Public ATS
adapters and deterministic research-query generation plug into the same
provenance-first source/job model. The historical `quant_recruiting` package
and `quant-recruiting` command remain compatibility aliases; `recruiting` is
the preferred CLI.
## V5 interactive AI boundary

V5 adds a human-operated synthesis boundary after deterministic acquisition. Task bundles contain selected database evidence and versioned instructions; structured results are validated and imported as drafts. No model API, browser automation, or automatic application action is part of this system.

## V6 application-artifact boundary

V6 adds a deterministic derivative layer after human approval. Structured candidate/application records remain canonical; `application_artifacts` stores immutable, versioned outputs. CV LaTeX/PDF, cover-letter Markdown/LaTeX/PDF, answer JSON/Markdown/DOCX, packet manifests, and the future browser payload are all regenerated from approved records and retain relational provenance links.

The local review workspace is bound to localhost by default. It can approve, reject, supersede, and edit drafts, but it does not submit applications. Approved artifacts are immutable; edits create new drafts and require renewed provenance review. The V7 browser boundary is deliberately limited to preparing a reviewed field payload and must stop before final submission.

## V8 local-first boundary

```text
shared PostgreSQL/Supabase --public intelligence--> local SQLite/cache
local SQLite/filesystem --private application work--> nowhere automatically
```

`get_shared_session()` and `get_local_session()` are separate. Private CLI
operations use `private_session_scope()` in `local_first` mode. Normal clients
use the V9 HTTPS read API rather than shared database credentials; direct
PostgreSQL transport remains for developer/admin workflows, migrations, and
tests. Local paths, AI bundles, conversation archives, artifacts, browser
profiles, and review state are private.
## V9 deployment topology

```text
             SHARED RECRUITING INTELLIGENCE
                  PostgreSQL / Supabase
                           │
                      Shared API
                           │ HTTPS GET
                           ▼
                 LOCAL RECRUITING APP
                           │
                     local SQLite
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
         ChatGPT        Claude         Gemini
```

The shared API knows only public recruiting intelligence. The local companion
owns candidate data, applications, artifacts, AI history, browser state, and
outcomes. EFDS may consume the shared API but never receives the local database.

V11 recruiting operations are also local-only: email, status outcomes, assessment
details, interview appointments, timelines, reminders, contacts, notes, notifications,
and preparation plans are written to SQLite. Browser preflight may pull a stale public
job snapshot, but it never sends application or email data.

## V10 browser boundary

Playwright runs entirely inside the local companion boundary. It reads a
verified local packet, persists inspection/fill/upload/validation evidence to
local SQLite and private files, and has no final-submit operation. Shared API
traffic is limited to explicitly requested public intelligence refreshes; form
labels, answers, candidate values, files, screenshots, and browser logs never
leave the device.
