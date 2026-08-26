# Recruiting Intelligence System

**A local-first recruiting operations platform for discovering opportunities, organizing public recruiting intelligence, tracking applications, and managing the recruiting lifecycle.**

Built as an end-to-end software engineering project, the system combines **data pipelines, PostgreSQL/Supabase, a versioned FastAPI service, local SQLite storage, browser automation, Gmail integration, background jobs, and a desktop-oriented application layer**.

### What this project demonstrates

* **End-to-end system architecture:** public data discovery → ingestion → normalization → storage → APIs → local application workflows.
* **Data engineering:** PostgreSQL/Supabase, SQLite, relational data modelling, migrations, immutable source artifacts, synchronization and provenance.
* **Backend engineering:** versioned FastAPI services, shared/local data boundaries, deterministic processing pipelines and background jobs.
* **Systems integration:** public ATS platforms, Gmail OAuth, browser automation and external search/data sources.
* **Privacy & security:** personal recruiting data remains local by default, credentials stay behind appropriate service boundaries, and shared services receive only explicitly permitted data.
* **Reliable automation:** bounded workflows, diagnostics, checkpoints, validation, failure recovery and human approval gates.

The project is designed around a simple principle: **automate recruiting operations and information management while keeping consequential application decisions under human control.**

## Core capabilities

**Opportunity intelligence** — discovers and tracks public job and company information across recruiting sources and supported ATS platforms.

**Application tracking** — maintains application state, recruiting timelines, assessments, interviews, deadlines and next actions.

**Research pipelines** — fetches, normalizes, versions and indexes public recruiting information while retaining source provenance.

**ATS interoperability** — detects and works with platforms including Greenhouse, Lever, Ashby, Workday, SmartRecruiters, iCIMS, Workable, BambooHR, SuccessFactors and Taleo, with capability levels based on available validation.

**Browser assistance** — provides conservative local form assistance using approved, deterministic information, with explicit pauses around unknown or sensitive fields and a mandatory human submission boundary.

**Email integration** — uses Google's read-only installed-app OAuth flow for local recruiting-email synchronization and status tracking.

**Local-first privacy** — separates shared public recruiting intelligence from private candidate and application information stored locally.

## Architecture

```text
Public Careers Sources / ATS Platforms
                  │
                  ▼
        Discovery + Collection
                  │
                  ▼
     Normalization + Provenance
                  │
          ┌───────┴───────┐
          ▼               ▼
 PostgreSQL/Supabase   Local SQLite
 Public Intelligence   Private Records
          │               │
          └───────┬───────┘
                  ▼
          Versioned FastAPI
                  │
                  ▼
      Local Recruiting Assistant
          │       │       │
          ▼       ▼       ▼
       Gmail   Timeline   Browser
        Sync    & Tasks   Assistance
```

## Technical stack

**Backend:** Python · FastAPI · PostgreSQL · Supabase · SQLite · SQLAlchemy · Alembic
**Automation:** Playwright · background jobs · Gmail OAuth · ATS adapters
**Data:** versioned ingestion · content hashing · provenance · synchronization · local caching
**Quality:** pytest · mypy · Ruff · fixture-based integration testing

## Safety and human control

The system is intentionally designed around human-controlled recruiting workflows:

* It **does not submit job applications**.
* Browser assistance stops before final submission.
* Sensitive, legal and unknown fields require human review.
* It does not solve or bypass CAPTCHAs, authentication, robots rules, rate limits or access controls.
* Gmail access is read-only and local.
* Personal application information remains local by default.
* Public and private data are separated by explicit architectural boundaries.

The candidate remains responsible for reviewing application information and making all consequential application decisions.
