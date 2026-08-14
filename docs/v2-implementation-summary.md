# V2 implementation summary

V2 adds an explicit discovery layer, company-domain and deterministic identity resolution, persisted discovered URLs, robust public fetching boundaries, Schema.org job extraction, deterministic role/cycle classification, job observations, incremental source/job timestamps, application candidate filtering, richer dossier exports, and PostgreSQL diagnostics.

The V2 migration is `20260812_0002`. It is additive and preserves V1 source/document/application history. The initial V1 migration was adjusted to remain a V1 snapshot when run on a fresh database; current model changes are applied by V2.

Still intentionally absent: search-engine discovery, authenticated or platform-specific scraping, social/news/video ingestion, LLM APIs, ChatGPT automation, CV/cover-letter generation, browser submission, Notion sync, EFDS publishing, and Gmail status detection.
