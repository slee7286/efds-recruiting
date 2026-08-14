# V3 generalization audit

## Scope inspected

Inspected the V2 repository tree, package and CLI names, README and V1/V2 documentation, environment/configuration, all SQLAlchemy tables and migrations, deterministic ingestion/discovery/jobs logic, seed data, and the complete unit/integration fixture suite.

## SAFE TO RENAME

- Human-facing descriptions, README titles, CLI help text, documentation filenames added in V3, and the project description can safely say “Recruiting Intelligence System”.
- New modules can use neutral names such as `ats`, `research_discovery`, `intelligence`, and `refresh`.

## SHOULD GENERALIZE

- `role_family` is currently a constrained string with only quant, engineering, data, trading, research, and `other` values. V3 should retain the column for compatibility while adding relational `role_families` and a nullable `role_family_id` on jobs.
- Skills currently contain a good quantitative hierarchy but lack finance, broader engineering, product, consulting, and professional skills.
- Application and interview terminology is flexible in several places, but status/event vocabulary and reports should gain normalized recruiting-stage entities without invalidating historical strings.
- The research provider boundary is already explicit for official sites; V3 can add ATS, search-result, source-registry, and public-resource providers without replacing the web collector.
- Export and AI-task structures should be renamed in content and extended to company/application dossiers, while retaining existing paths and manifests.

## KEEP FOR BACKWARD COMPATIBILITY

- Python package `quant_recruiting` and CLI executable `quant-recruiting` should remain. Renaming the installed package now would break Alembic imports, existing scripts, migration modules, and user workflows. Add a `recruiting` executable alias pointing to the same Typer app instead.
- Existing table names (`companies`, `jobs`, `applications`, `research_sources`, etc.), `role_family` values, `internship_cycle`, `first_oa_reported_at`, and historical application statuses/events must remain valid.
- The initial and V2 Alembic revisions must not be rewritten destructively. V3 is additive.
- Existing quant seed skills and quant fixtures remain valid; they become one branch of the broader taxonomy.

## ACTUALLY QUANT-SPECIFIC

- Quantitative research/trading role rules and probability/trading skill seeds are genuinely quant-specific and should remain as taxonomy entries, not architecture assumptions.
- The V2 `quant-recruiting` naming, README language, default user-agent wording, and default config examples are product-language assumptions and will be generalized.
- The V2 `first_oa_reported_at` field is historical data vocabulary, not a requirement that every role has an OA. New stage records will support coding, numerical, psychometric, HireVue, case, assessment-centre, superday, and other stages.

## V3 naming decision

Do not rename the Python package or existing CLI. This is the lowest-risk path because migrations import `quant_recruiting`, the installed entry point is already used in documentation, and existing tests/imports depend on it. V3 changes the product language to “Recruiting Intelligence System” and adds a `recruiting` console-script alias for new workflows.
