# Source ingestion

The V4 pipeline is explicit:

```text
discovery → fetch → raw artifact → normalization → structured extraction → document/claims
```

`research_sources` identify logical URLs. `source_artifacts` retain immutable
content-addressed retrievals for HTML, PDF, JSON, XML, text, and future media.
`research_documents` retain normalized versions. Failures are persisted and
source quality/claim type remain separate from extraction confidence.
