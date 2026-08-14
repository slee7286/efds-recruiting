# Recruiting Intelligence System

This is a private, local-first system for tracking recruiting research, jobs, applications, preparation, and candidate evidence across finance, quantitative, technology, consulting, and other graduate roles. Public recruiting intelligence can be synchronized from PostgreSQL/Supabase into a local cache; personal applications, CVs, answers, AI chats, browser state, and outcomes stay on the user's computer by default. It does not call an LLM, automate AI-provider websites, submit applications, or bypass authentication, CAPTCHAs, robots rules, rate limits, or access controls. V10 provides conservative local form autofill that stops before final submission.

## Architecture

### V13 operational hardening

V13 adds local Gmail OAuth/incremental synchronization, sanitized email fixture
capture, evidence-backed ATS capability reports, dogfood metrics, and a system
readiness report. Gmail uses Google's read-only installed-app flow; tokens and
messages remain local. Configure a desktop OAuth client, then run:

```text
recruiting email connect gmail
recruiting email sync
recruiting readiness system
recruiting browser ats-status
recruiting browser dogfood-report
```

No browser run clicks the final application submit control. No personal email,
application, CV, answer, browser, or AI data is sent to the shared intelligence
service.

PostgreSQL/Supabase is the shared source for public intelligence, exposed to normal clients through the versioned FastAPI shared API. SQLite is the local canonical source for private candidate/application data. See [docs/local-first-architecture.md](docs/local-first-architecture.md), [docs/shared-api.md](docs/shared-api.md), [docs/shared-vs-local-data.md](docs/shared-vs-local-data.md), [docs/architecture.md](docs/architecture.md), and [docs/data-model.md](docs/data-model.md).

The database is intentionally separate from the EFDS website/database. A future integration may publish only a curated, sanitized subset through an explicit publishing layer; it must never provide unrestricted cross-database access.

## Installation

Use Python 3.13+, PostgreSQL, and a virtual environment. Then install the package and development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Copy `.env.example` to `.env`. Local SQLite works without a shared database. Set `SHARED_DATABASE_URL` when public intelligence sync or shared discovery is needed. `LOCAL_DATA_DIR` defaults to the OS application-data directory.

## Database and CLI

```bash
quant-recruiting db check
quant-recruiting db upgrade
recruiting seed skills
recruiting seed taxonomy
quant-recruiting seed companies
quant-recruiting company add "Example Firm"
quant-recruiting company list
quant-recruiting job add example-firm "Quantitative Research Intern" https://example.com/job --role-family quantitative_research
quant-recruiting source add-url https://example.com --company-slug example-firm --source-type official_website
quant-recruiting company add-domain example-firm example.com --domain-type corporate
quant-recruiting discover website example-firm
quant-recruiting discover jobs example-firm
quant-recruiting job sync example-firm
quant-recruiting applications candidates
quant-recruiting research export example-firm
quant-recruiting ai prepare-company example-firm
recruiting ai prepare-application <application-id>
recruiting ai prepare-match example-firm
recruiting ai readiness <application-id>
recruiting ai validate <task-id>
recruiting ai import <task-id>
recruiting ai approve <task-id> --approved-by reviewer
recruiting applications quality <application-id>
recruiting ats detect example-firm
recruiting ats sync example-firm
recruiting research discover example-firm --role-family investment_banking --cycle 2027
recruiting refresh due
recruiting research search example-firm --category interview_process --limit 5
recruiting research queue example-firm --min-score 0.5
recruiting research fetch example-firm --max-items 10
recruiting research coverage example-firm
recruiting intelligence topics example-firm --role software_engineering
recruiting intelligence process example-firm
recruiting prep report example-firm --role software_engineering
recruiting application readiness <application-id>
recruiting artifact render-cv <application-id>
recruiting artifact render-cover-letter <application-id>
recruiting artifact render-answers <application-id>
recruiting artifact build-packet <application-id>
recruiting artifact verify-packet <application-id>
recruiting review serve
recruiting sync pull --company example-firm
recruiting sync status
recruiting app serve --open-browser
recruiting app open
recruiting api serve
recruiting api check
recruiting setup browser
recruiting local doctor
recruiting local backup
recruiting migrate personal-to-local --dry-run
recruiting ai open <task-id> --provider claude
recruiting ai import-conversations chatgpt C:\Downloads\chatgpt-export --dry-run
recruiting ai conversations search "why this firm"
```

The source command respects normal public HTTP behaviour and also accepts `file://` URLs for deterministic local/test documents. Browser autofill is a separate local-only V10 workflow.

Discovery, fetching, normalization, extraction, and synthesis are separate layers. V3 adds relational role families/stages, public ATS adapters, deterministic research queries, source classification, and refresh targets. See [docs/job-discovery.md](docs/job-discovery.md), [docs/ats-adapters.md](docs/ats-adapters.md), [docs/research-discovery.md](docs/research-discovery.md), and [docs/supabase-setup.md](docs/supabase-setup.md).

V4 adds optional configured search execution, a scored research-fetch queue, immutable raw artifacts, PDF normalization, public-source normalizers, deterministic interview extraction, preparation-resource sections, coverage reports, and richer AI manifests. Set `SEARCH_PROVIDER=brave` and `SEARCH_API_KEY` before live search; without them, search execution fails clearly while fixture/offline workflows remain available.

V5 adds versioned interactive-AI task contracts. The workflow is prepare a bounded bundle, use a human-operated AI session, save `output/result.json`, validate, import as draft data, and explicitly approve after review. Candidate evidence is private and only evidence marked `approved_for_application` is included in application tasks. See [docs/interactive-ai-workflow.md](docs/interactive-ai-workflow.md), [docs/ai-task-contracts.md](docs/ai-task-contracts.md), and [docs/application-intelligence.md](docs/application-intelligence.md).

V6 turns approved drafts into deterministic application artifacts. The canonical answer records produce byte-preserving JSON, Markdown, and DOCX outputs; approved CV records produce LaTeX and validated PDFs; packets include a machine-readable `application_form_payload.json` for a future browser-autofill system. Run the artifact commands above, verify the packet, then review locally with `recruiting review serve`. See [docs/application-artifacts.md](docs/application-artifacts.md), [docs/application-packets.md](docs/application-packets.md), [docs/review-workspace.md](docs/review-workspace.md), and [docs/browser-autofill-contract.md](docs/browser-autofill-contract.md).
V8 makes the data boundary explicit: public data may pull down; private data does not push up automatically. The provider-neutral AI workspace opens a user-selected ChatGPT, Claude, Gemini, or custom provider without typing or scraping, and supplied conversation exports are archived locally. See [docs/shared-sync.md](docs/shared-sync.md), [docs/ai-provider-launcher.md](docs/ai-provider-launcher.md), and [docs/private-data-boundary.md](docs/private-data-boundary.md).

V9 adds the read-only shared-intelligence API and the local Recruiting Assistant companion. New installations use `SHARED_TRANSPORT=api` and `SHARED_API_URL`; direct PostgreSQL mode remains for developers, admins, migrations, and tests. The Windows PyInstaller build foundation is in `packaging/`; it does not bundle private data, credentials, browser sessions, MiKTeX, or Chromium. See [docs/local-companion.md](docs/local-companion.md), [docs/shared-api-sync.md](docs/shared-api-sync.md), and [docs/windows-packaging.md](docs/windows-packaging.md).

V10 adds local-only Playwright autofill. Install/check Chromium with
`recruiting setup browser --install`, then use:

```bash
recruiting application readiness <application-id>
recruiting artifact verify-packet <application-id>
recruiting browser preflight <application-id>
recruiting browser run <application-id>
```

The browser inspects first, fills only approved deterministic values, pauses
for sensitive/legal/unknown fields, verifies exact answers and approved
documents, and stops before final submission. The user reviews the visible
page and submits manually. See [docs/playwright-autofill.md](docs/playwright-autofill.md),
[docs/browser-human-submit-gate.md](docs/browser-human-submit-gate.md), and
[docs/browser-privacy.md](docs/browser-privacy.md).

V11 closes the local operational loop with recruiting-email import/classification,
application status events, assessment deadlines, interview appointments, ICS export,
timeline/actions/reminders, deterministic preparation plans, and local companion pages:

```bash
recruiting email import confirmation.eml
recruiting timeline show --upcoming
recruiting assessment list
recruiting interview list
recruiting prep today
recruiting notifications list --deliver
```

Email is local-only. Gmail uses a legitimate OAuth/provider boundary; no Gmail web
scraping, password handling, sending, auto-booking, or automatic replies are implemented.
See [docs/email-ingestion.md](docs/email-ingestion.md),
[docs/recruiting-timeline.md](docs/recruiting-timeline.md), and
[docs/preparation-plans.md](docs/preparation-plans.md).

V12 hardens that workflow for real ATS variation. `recruiting browser ats-status`
shows explicit capability levels for Greenhouse, Lever, Ashby, Workday,
SmartRecruiters, iCIMS, Workable, BambooHR, SuccessFactors, Taleo, and generic
forms. Workday/iCIMS remain conservative partial/experimental adapters where
tenant behavior is not fixture-proven. Browser attempts/checkpoints, sanitized
diagnostics, inspect-only fixture capture, and restart history are local-only:

```bash
recruiting browser ats-status
recruiting browser diagnostics <run-id>
recruiting browser privacy-check <run-id>
recruiting browser restart <run-id>
recruiting background run-once
recruiting background install
recruiting job-alert add "London SWE" --role-family software_engineering --location London
```

The background runner performs bounded local reminders, job alerts, public sync,
and active-job freshness work. It never opens a browser, sends email, solves a
CAPTCHA, or submits an application. See [docs/ats-capabilities.md](docs/ats-capabilities.md),
[docs/browser-recovery.md](docs/browser-recovery.md), and
[docs/background-runner.md](docs/background-runner.md).

## Filesystem layout

```text
data/raw/<company>/<source-id>/<content-hash>.html
data/normalized/<company>/<source-id>/v<version>-<content-hash>.md
data/ai_queue/<task-id>/{manifest.json,instructions.md,input/,output/result.json,validation/}
research/<company>/{_index.md,sources/,manifests/sources.json}
~/.recruiting-assistant/{recruiting.db,profile/,applications/,conversations/,research-cache/,exports/,browser-profiles/,logs/,cache/,app.lock}
```

Raw and normalized artifacts are versioned/content-addressed and are not silently replaced. The database stores the current source pointer and all historical document versions.

## Provenance principles

URLs are not enough: each fetched source records canonical URL, retrieval/observation timestamps, HTTP status, content hash, quality, and filesystem paths. Claims retain source and optional document references and are typed as fact, inference, anecdote, or opinion. Official careers material and candidate anecdotes therefore remain distinguishable.

## Tests and quality

Run `ruff check .`, `mypy src`, and `pytest`. Database-backed tests should use an isolated PostgreSQL database configured through the test environment; pure service tests do not require a database. Run `alembic current` and `alembic upgrade head` against the configured PostgreSQL database.

## Roadmap

V12 should prioritize additional ATS adapters, real-world browser-autofill hardening,
optional Notion export/sync, calendar provider integration, and a packaged Windows
installer/update workflow. Personal application data must remain local unless the user
explicitly exports or publishes a sanitized subset.
