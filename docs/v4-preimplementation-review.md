# V4 pre-implementation review

## Current V3 state

V3 already has a provenance-first `research_sources`/`research_documents` pair,
content hashing and document versions, deterministic website discovery, public
Greenhouse/Lever/Ashby job adapters, research query generation, relational role
families/interview stages/resources, refresh targets, company exports, and AI
context manifests. The `recruiting` CLI alias and the historical
`quant_recruiting` package remain compatible.

## Gaps to address

- `SearchProvider` only models an in-memory result shape and does not execute a
  configured legitimate provider. Search results are not yet promoted into the
  discovered-URL queue.
- The fetcher accepts HTML/XML/JSON but rejects PDFs and other binary artifacts;
  raw content is stored through source paths rather than an explicit immutable
  artifact row.
- HTML normalization is deterministic but broad (`h1`/`p`/`li`/table cells),
  without article metadata, page-aware PDF text, or source-specific metadata.
- There is no separate extraction protocol for recruiting events, interview
  questions, topic tags, or preparation resources.
- Existing interview tables can store questions but lack a conservative,
  provenance-span extraction workflow and reporting utilities.
- Existing resources have skill/role/company/stage mappings but no section or
  chapter hierarchy.
- Exports and AI manifests are useful V3 indexes but do not yet include
  interview evidence, claims, resources, coverage, or contradiction summaries.
- Refresh primitives calculate due/backoff state but do not dispatch category-
  specific acquisition work.

## V4 design decisions

V4 will remain additive. It will introduce `source_artifacts`, a fetch queue,
search usage records, resource sections, and extraction evidence tables where
relational querying is valuable. Existing source/document rows remain the
canonical logical identity; artifacts represent immutable retrieved bytes, and
documents represent normalized text versions.

The acquisition pipeline remains explicit:

```text
discovery → fetch → raw artifact → normalization → extraction → document/claims
```

Provider implementations will be conservative and injectable. Search execution
will fail clearly when no provider is configured. PDF, YouTube, Reddit, GitHub,
news, and forum support will preserve source quality and platform restrictions;
unsupported or unavailable content will remain a discovered candidate rather
than being fabricated.

## Provenance risks to prevent

- Do not overwrite a source's historical document or raw artifact.
- Do not convert approximate recruiting language into exact dates.
- Do not treat a search result as a verified fact.
- Default candidate discussion claims to anecdote and lower quality.
- Keep extracted text spans/original wording alongside normalized entities.
- Keep personal candidate evidence separate from firm/interview evidence.

## Verification plan

Use local HTML/PDF/JSON/transcript fixtures for deterministic tests. Run Ruff,
mypy, pytest, Alembic offline checks, CLI smoke tests, and live PostgreSQL tests
only when `DATABASE_URL`/`TEST_DATABASE_URL` is configured. No live credentials
are currently assumed.
