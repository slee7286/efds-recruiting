# V6 pre-implementation review

## Existing V5 strengths

- Candidate experiences and evidence are relational and candidate-private. Evidence already has `approved_for_application`, which is the right gate for application context.
- CV versions, CV bullets, and CV-to-evidence joins exist. They provide a useful source representation, but there is no master-CV selection model and no deterministic renderer yet.
- Application questions and versioned answers exist, including specificity and approval fields. There is no canonical JSON/Markdown/DOCX archive or exact-output verifier.
- V5 AI tasks, runs, outputs, arguments, requirements, gaps, and provenance contracts provide the correct upstream inputs. Imported content is draft-oriented, but artifacts and review events are not yet modeled.
- The existing application export is a deterministic context export, not an application packet. It must remain compatible while V6 adds packet directories and artifact manifests.
- The CLI is a Typer monolith with grouped commands. V6 can add `artifact`, `application`, `candidate`, and `review` groups without changing existing command names.

## Gaps and decisions

### Additive schema

V6 will add application artifacts, artifact provenance joins, candidate profile fields, sensitive-field records, master-CV sections/entries, cover-letter blocks, review events, and browser-autofill contract tables. Existing V1–V5 tables and migrations remain unchanged; a new migration will use existence checks for fresh and upgraded databases.

### Canonical representations

- Structured database records are canonical; PDF/DOCX/Markdown/LaTeX are versioned derivatives.
- Approved artifact rows are immutable. A new edit creates a draft/version and may supersede a previous approved artifact only explicitly.
- Written answers are rendered from approved `application_answers` rows without rewriting or truncation.
- CV bullets and cover-letter blocks retain relational evidence/source mappings.

### Rendering

LaTeX is the preferred CV and cover-letter renderer. The implementation will detect `pdflatex` and fail clearly if unavailable. PDF text extraction will use the existing `pypdf` dependency. DOCX archives will use `python-docx`; no proprietary fonts or OCR are required.

### Review and readiness

V6 needs local-only review routes, deterministic approval/edit events, packet verification, and a readiness service. Readiness is a gate, not an application submission action. Sensitive values are explicit user-entered records only; unknown values remain unresolved.

### V7 handoff

The packet will include an approved-only `application_form_payload.json` and a reserved `browser/` directory. V6 defines browser field categories and audit tables but does not inspect forms, upload files, click submit, bypass CAPTCHAs, or automate a browser.

## Intentional non-goals

No browser automation, final submission, semantic provenance inference after edits, automatic CV rewriting, automatic cover-letter generation, or public review server will be added.

