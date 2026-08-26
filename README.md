# Recruiting Intelligence System

**A local-first recruiting operations platform for discovering opportunities, organizing public recruiting intelligence, tracking applications, and managing the recruiting lifecycle.**

Built as an end-to-end software engineering project, the system combines **data pipelines, PostgreSQL/Supabase, a versioned FastAPI service, local SQLite storage, browser automation, Gmail integration, background jobs, and a local application layer**.

> **This project automates recruiting operations and information management; it is not an automated application-submission system.**

## What this project demonstrates

* **End-to-end system architecture** — public data discovery → ingestion → normalization → storage → APIs → local application workflows.
* **Data engineering** — PostgreSQL/Supabase, SQLite, relational modelling, migrations, immutable source artifacts, synchronization and provenance.
* **Backend engineering** — versioned FastAPI services, shared/local data boundaries, deterministic processing pipelines and background jobs.
* **Systems integration** — public ATS platforms, Gmail OAuth, browser automation and external search/data sources.
* **Privacy & security** — personal recruiting data remains local by default, credentials stay behind appropriate service boundaries, and shared services receive only explicitly permitted data.
* **Reliable automation** — bounded workflows, diagnostics, checkpoints, validation, failure recovery and human approval gates.

The system is designed around a simple principle: **automate recruiting operations and information management while keeping consequential application decisions under human control.**

<br>

## Core capabilities

### Opportunity intelligence

Discovers and tracks public job and company information across recruiting sources and supported ATS platforms. Public information is collected through deterministic discovery, fetching and normalization pipelines with source provenance retained.

### Application tracking

Maintains application state, recruiting timelines, assessments, interviews, deadlines, reminders and next actions in a structured local system.

### Research pipelines

Fetches, normalizes, versions and organizes public recruiting information. Source records retain provenance including canonical URLs, observation timestamps, content hashes and source classifications.

### ATS interoperability

Detects and works with common recruiting platforms including **Greenhouse, Lever, Ashby, Workday, SmartRecruiters, iCIMS, Workable, BambooHR, SuccessFactors and Taleo**, with conservative capability levels where platform behavior has not been fully validated.

### Browser assistance

Provides conservative local browser assistance using approved, deterministic information. The browser inspects forms first, pauses around sensitive, legal or unknown fields, validates known information and **stops before final submission**.

### Email integration

Uses Google's read-only installed-app OAuth flow for local recruiting-email synchronization. Recruiting communications can be associated with application status events, assessments, interviews and deadlines without providing the system with email-sending capability.

### Local-first privacy

Separates shared **public recruiting intelligence** from private candidate and application information. PostgreSQL/Supabase serves shared public intelligence while SQLite is the canonical local store for private records.

<br>

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

### Data boundary

```text
SHARED
Public company information
Public job information
Public recruiting research
Public ATS metadata
        │
        │ explicit synchronization
        ▼
LOCAL
Application records
Candidate information
Email-derived status
Assessments & interviews
Browser state
Personal recruiting history
```

Private application information does **not** automatically push back into the shared intelligence service.

<br>

## Technical stack

| Area                             | Technologies / Design                                               |
| -------------------------------- | ------------------------------------------------------------------- |
| **Backend**                      | Python · FastAPI · SQLAlchemy · Alembic                             |
| **Databases**                    | PostgreSQL · Supabase · SQLite                                      |
| **Browser automation**           | Playwright                                                          |
| **Authentication / integration** | Gmail OAuth · provider boundaries                                   |
| **Data engineering**             | Versioned ingestion · content hashing · normalization · provenance  |
| **APIs**                         | Versioned FastAPI shared-intelligence API                           |
| **Background processing**        | Bounded local jobs · reminders · synchronization · freshness checks |
| **Quality**                      | pytest · mypy · Ruff · fixture-based integration testing            |
| **Privacy architecture**         | Local/private and shared/public data separation                     |

<br>

## Human control and safety boundaries

The system deliberately maintains explicit boundaries around consequential recruiting actions:

* **No automatic application submission.**
* Browser assistance stops before the final submission control.
* Sensitive, legal and unknown fields require human review.
* The system does not bypass authentication or access controls.
* It does not solve or bypass CAPTCHAs, robots rules or rate limits.
* Gmail access is read-only.
* It does not automatically send emails or book interviews.
* Personal application information remains local by default.
* Shared and private data are separated by explicit architectural boundaries.
* Browser operations maintain diagnostics and checkpoints for review and recovery.

The candidate remains responsible for reviewing application information and making all consequential application decisions.

<br>

## Engineering highlights

### Local-first architecture

The platform intentionally uses two data domains:

**PostgreSQL/Supabase** acts as the shared source for public recruiting intelligence and is exposed to ordinary clients through a versioned API.

**SQLite** acts as the local canonical source for private candidate and application information.

This allows public intelligence to be synchronized while keeping personal recruiting information on the user's machine by default.

### Provenance and reproducibility

Fetched sources retain canonical URLs, timestamps, HTTP metadata, content hashes and source classifications. Raw and normalized artifacts are versioned/content-addressed rather than silently overwritten.

This makes it possible to distinguish current information from historical versions and trace derived recruiting intelligence back to its source.

### Defensive browser automation

Browser automation is intentionally conservative rather than submission-oriented.

The system supports:

```text
inspect
   ↓
identify fields
   ↓
match approved deterministic information
   ↓
pause on unknown / sensitive fields
   ↓
verify populated information
   ↓
human review
   ↓
STOP before submission
```

Browser attempts maintain checkpoints, sanitized diagnostics, failure categories and restart history.

### Recruiting lifecycle integration

Recruiting emails, application status events, assessments and interviews feed a common local timeline that supports:

* upcoming deadlines
* assessment tracking
* interview appointments
* reminders
* preparation schedules
* application status history
* next-action tracking

### Operational hardening

The system includes:

* Gmail incremental synchronization
* local OAuth credential handling
* sanitized test-fixture capture
* ATS capability reporting
* browser diagnostics
* browser recovery/checkpoints
* bounded background processing
* readiness checks
* local backup support
* application-state history

These features are intended to make the project usable as an actual local application rather than only a collection of scripts.

<br>

## Supported ATS platforms

The system maintains explicit capability information for:

* Greenhouse
* Lever
* Ashby
* Workday
* SmartRecruiters
* iCIMS
* Workable
* BambooHR
* SuccessFactors
* Taleo
* generic web forms

Support is intentionally conservative: platform behavior that has not been sufficiently validated is represented as partial or experimental rather than assumed to work.

<br>

## Development

Install the Python package and development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Run quality checks with:

```bash
ruff check .
mypy src
pytest
```

Database schema changes are managed through Alembic:

```bash
alembic current
alembic upgrade head
```

Detailed installation, CLI, architecture, integration and development documentation is available under [`docs/`](docs/).

<br>

## Design principles

1. **Human control over consequential actions**
2. **Private data stays local by default**
3. **Public and private data have explicit boundaries**
4. **Source provenance is retained**
5. **Automation fails conservatively**
6. **Unknown states require human review**
7. **External systems are accessed through legitimate provider boundaries**
8. **Capabilities are reported based on evidence rather than assumed support**

The result is a recruiting operations platform designed to demonstrate **end-to-end backend engineering, data architecture, systems integration, privacy-aware design and reliable human-in-the-loop automation**.
