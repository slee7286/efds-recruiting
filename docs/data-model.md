# Data model

The model is split into bounded domains:

- `companies`, aliases, `jobs`, and `applications` represent recruiting entities and immutable application history.
- `research_sources`, `research_documents`, and `research_claims` represent provenance-first research. A source has one canonical URL and many document versions.
- `recruiting_cycles`, events, interview reports, questions, attempts, and skills/resources support temporal recruiting intelligence and preparation.
- `candidate_experiences`, evidence, CV versions, application questions, and answers are private candidate/application data.
- `ai_tasks` records handoff state without coupling the system to an LLM provider.

V2 adds `company_domains`, `discovered_urls`, `job_observations`, and `fetch_errors`. Domain ownership is not inferred automatically; domains are explicit and may carry source/verification metadata. Discovered URLs retain how they were found and their relevance/category evidence. Job observations preserve historical posting changes without creating duplicate logical jobs.

Foreign keys and association tables are explicit. JSONB is reserved for flexible metadata, section context, and future fields that are not yet queried as relational entities.
# V3 entities

V3 adds hierarchical `role_families` and `interview_stages`, `company_ats`,
research query/result records, firm intelligence items with provenance joins,
candidate-firm matches, role/company/stage resource mappings, answer
specificity storage, and `refresh_targets`. Existing string role/stage fields
remain for historical compatibility; relational taxonomy and manual locks are
the extensible path.
## V5 application intelligence

AI task runs and outputs preserve repeated attempts. Application requirements, gaps, arguments, CV bullets, and candidate stories are structured records. Join tables retain candidate-evidence and research-source provenance. Candidate evidence has explicit application approval, and imported AI artifacts remain drafts.

## V6 artifacts and review

V6 adds `candidate_profiles`, `candidate_sensitive_fields`, `candidate_cv_sections`,
`candidate_cv_entries`, `application_artifacts`, and `artifact_provenance`. Answer
and cover-letter provenance is also represented relationally. `review_events`
records human actions. `browser_fill_runs` and `browser_field_mappings` are
reserved audit structures for V7 and do not execute browser automation.

Artifacts are versioned by application and type. An approved artifact cannot be
mutated in place; a later approved version supersedes it while preserving the
older row. The packet verifier checks artifact ownership, approval, byte hashes,
exact answer text in all answer formats, and current approved-version references.

## V8 local-first entities

The local bootstrap schema reuses stable UUID-backed public model rows as an
offline cache and adds `local_shared_cache`, `local_sync_state`, and
`local_application_references`. Private records remain in local copies of the
candidate/application tables. Local-only conversation tables are
`ai_conversations`, `ai_conversation_messages`, attachments, links, and
annotations. `local_publish_intents` is only a future explicit publication
contract; it is not an upload queue.

SQLite is not run through the PostgreSQL Alembic chain. `upgrade_local()` owns a
dedicated local schema version and creates only the selected cache/private
tables plus FTS5. The shared migration chain remains PostgreSQL-specific and
backward compatible.

## V9 transport boundary

The shared database is exposed to normal clients through read-only, versioned
`/api/v1` DTOs. The API exposes public companies, jobs, provenance-backed firm
intelligence, recruiting evidence, resources, and sync changes; it has no
candidate, application, artifact, conversation, browser, or sensitive-field
routes. Local sync applies validated snapshots and tombstones transactionally
to the SQLite cache. Direct shared PostgreSQL access is retained only for
backend/admin/developer workflows.

## V10 local browser entities

The local schema version is now 2. V10 adds `browser_runs`, `browser_pages`,
`browser_fields`, local field mappings, fill attempts, uploads, validation
errors, field aliases, reusable candidate form values, and application-only
form values. The historical V6 browser reservation tables remain for backward
compatibility; V10 browser telemetry is written only to the local selected
tables.
