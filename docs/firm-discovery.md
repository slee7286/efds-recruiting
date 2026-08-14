# Firm research discovery

Firm discovery starts from explicitly configured company domains and careers URLs. Each candidate URL is persisted with its discovery method, probable source category, relevance score, reasons, timestamp, and metadata before ingestion.

Rule-based categories include firm overview, careers, internship, role description, culture, technology, research, people, news, insight, publication, and other. Categories are hints, not claims. The source row remains provenance-first and later exports retain source IDs, URLs, quality, hashes, and retrieval times.

The dossier exporter creates deterministic indexes under `research/<company>/`:

- `firm/` for official pages, culture, research, and technology;
- `recruiting/` for jobs and cycle records;
- `sources/` for YAML-frontmatter source documents;
- `manifests/` for machine-readable source and job records.

No prose conclusion or recruiting-stage synthesis is generated automatically. The AI queue creates reviewable context files and instructions for a later interactive session, with explicit rules against unsupported claims.
