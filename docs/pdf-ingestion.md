# PDF ingestion

Public PDFs are fetched with the shared timeout, size, redirect, and user-agent
policy. The original bytes are retained as a hashed `source_artifacts` row and
on disk. `pypdf` extracts text without OCR and normalized output adds
`<!-- page: N -->` markers. Malformed, encrypted, or textless PDFs produce a
queryable fetch/normalization failure; OCR is intentionally deferred.
