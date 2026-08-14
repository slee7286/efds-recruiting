# V5 pre-implementation review

## Scope

V4 already separates discovery, fetching, normalization, extraction, provenance, and deterministic exports. The V5 work should extend that foundation with interactive-AI task contracts and reviewable imports; it should not add an API client or automate an AI user interface.

## Findings

### SAFE TO RENAME

- None of the existing database tables should be renamed in V5. The package and CLI already expose the preferred `recruiting` compatibility entry point, while the historical `quant_recruiting` import path is still used by migrations and tests.
- New task names can use general recruiting terminology. The existing `company_research_synthesis` task remains readable for backward compatibility, with new V5 task types added alongside it.

### SHOULD GENERALIZE

- `AITask` currently stores only a task identity, filesystem paths, lifecycle status, and free-form metadata. It needs prompt/schema versioning, validation state, approval state, and preserved run/output records.
- The current company task bundle has useful evidence files but uses a V4-era flat layout. V5 should add the standard `input/`, `output/`, and `validation/` directories without deleting the old deterministic exports.
- Candidate evidence has confidence but no explicit application-approval or evidence-quality state. Application workflows need to select only active, approved evidence.
- Existing firm intelligence and candidate-firm match tables are suitable foundations. Imports need task provenance, draft state, source/evidence join rows, and deterministic validation before persistence.
- Application answers already have approval and specificity fields. They need structured task import and strict question/limit/evidence validation.
- CV versions currently represent document-level versions only. A bullet-level model and evidence join are required to preserve provenance for tailored drafts.
- Interview questions already carry source and extraction provenance, but should distinguish observed questions from practice/generated variants.

### KEEP FOR BACKWARD COMPATIBILITY

- All V1–V4 migrations and existing table names.
- Both `quant-recruiting` and `recruiting` entry points.
- Existing deterministic company exports and V4 AI manifest files; V5 will add files rather than silently remove them.
- Existing `company_research_synthesis` tasks and status values. Approval is represented by a separate approval state so the existing status constraint remains valid.

### ACTUALLY QUANT-SPECIFIC

- No generic V5 workflow should assume probability, statistics, OAs, or quant interview stages. Those remain seeded skills/role families and fixture data only.
- Existing quant-oriented seed names and historical documentation may remain as data examples, but application analysis, argument generation, CV tailoring, answer validation, and interview preparation must operate from role/job evidence and role-family mappings.

## Planned V5 changes

1. Add additive schema objects for prompt versions, task runs/outputs, application arguments and gaps, CV bullets, candidate stories, and evidence joins; add nullable/approved metadata to existing records.
2. Add versioned prompt templates and Pydantic v2 contracts for all interactive-AI task types.
3. Add a task preparation service that creates a compact, inspectable filesystem bundle and readiness summary.
4. Add validation/import services that reject unsupported IDs, invalid limits, invalid confidence/specificity, and unapproved candidate evidence. Imported records remain drafts.
5. Add CLI commands for preparation, validation, import, approval, diffing, readiness, and application quality reporting.
6. Add fixture-based tests and documentation covering quant, finance, and software-engineering examples without external AI calls.

## Migration strategy

The new migration will be additive and idempotent where possible. Models remain the canonical schema definition for fresh test databases, while the migration uses existence checks for databases upgraded from V1–V4. No historical research or AI task output is overwritten.

