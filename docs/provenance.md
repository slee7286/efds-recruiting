# Provenance

Every source has a canonical URL, source type, quality classification, retrieval timestamp, content hash, and optional raw/normalized artifact paths. Re-fetching identical content reuses the existing document version. Changed content retains the old document and creates a new version; raw HTML is content-addressed.

Claims point to their source and optionally to the exact normalized document. Claim types are deliberately explicit: `fact`, `inference`, `anecdote`, and `opinion`. Confidence and validity/observation timestamps are stored alongside the claim. A low-quality anecdote can be useful recruiting intelligence, but it must not be represented as an official fact.

The provenance invariants are explicit: a canonical source URL remains one logical source across content changes; changed content creates a historical document version; every discovered URL records discovery method, reason, score, and time; every job records first/last observation and `job_observations`; ATS payloads remain attached to job observations; every export source carries its database source ID and content hash. Search results are candidates rather than verified claims. Fetch failures are persisted separately with operation, error type, message, retryability, and time.

Exports reproduce source IDs, hashes, quality, URLs, and retrieval times in YAML frontmatter. AI task instructions require every synthesized claim to retain source IDs and prohibit invented facts or mixing company research with personal candidate evidence.
## V5 synthesis provenance

Interactive-AI outputs are accepted only when schema-valid and referentially valid. Company-specific claims must cite company-scoped source IDs; personal claims must cite approved candidate-evidence IDs. Prompt versions, task IDs, run files, validation results, and import timestamps are retained. Approval is a separate human-controlled state.
