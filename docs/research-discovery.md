# Research discovery

Research discovery generates deterministic, reviewable queries and persists
search candidates. Search results are discovery evidence, not verified facts.
The `SearchProvider` protocol leaves the external search service configurable;
the repository does not scrape Google or Bing result pages and does not require
an API key for local query generation.

URL classification recognizes official/ATS pages, news, reports/PDFs, Reddit,
YouTube, GitHub, and unknown sources. Specialized ingestion remains separate:
DISCOVERY → FETCHING → NORMALIZATION → EXTRACTION → SYNTHESIS.
