# Job discovery

V2 separates discovery from ingestion:

```text
company domains -> robots/sitemaps/internal links -> discovered_urls -> public fetch -> JobPosting -> jobs + job_observations
```

`OfficialSiteDiscoveryProvider` uses only company-controlled public domains, robots.txt, sitemap declarations/indexes, and bounded internal-link traversal. It applies configurable page/depth limits, denied paths, allowed domains, relevance scoring, content-size limits, retries, redirects, and per-host delay. It does not use search engines, authenticated ATS APIs, LinkedIn, or anti-bot bypasses.

Job pages are recognized through public Schema.org `JobPosting` JSON-LD. Malformed JSON-LD is ignored. Role-family and internship-cycle classification are deterministic and retain method, confidence, and original cycle wording in metadata.

Job identity prefers `(company, external_id)` when an identifier exists and otherwise `(company, canonical_job_url)`. The logical job row is updated when content changes; `job_observations` retains the observed hash, title, deadline, status, structured data, source URL, and observation time. A sync can close previously open official jobs that were not observed in the bounded run; manual jobs are not closed by this process.

Commands:

```bash
quant-recruiting discover website jane-street
quant-recruiting discover careers jane-street
quant-recruiting discover jobs jane-street
quant-recruiting discovered list jane-street
quant-recruiting source ingest-discovered jane-street
quant-recruiting job sync jane-street
```
# V3 ATS path

Public ATS detection and synchronization are separate from company-site
discovery. Greenhouse, Lever, and Ashby postings are normalized into the same
logical `jobs` table and append `job_observations`; manual role corrections can
be locked so deterministic refreshes do not overwrite them.
