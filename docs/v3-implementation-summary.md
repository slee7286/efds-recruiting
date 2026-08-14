# V3 implementation summary

V3 generalizes the product language while retaining `quant_recruiting` and
`quant-recruiting` as compatibility surfaces. The new `recruiting` command is
the preferred entry point. Additive migration `20260812_0003` adds role
families, interview stages, ATS configurations, research queries/results, firm
intelligence mappings, resource mappings, specificity storage, and refresh
targets.

Implemented foundations include deterministic finance/SWE/quant classification,
Greenhouse/Lever/Ashby public adapters, URL source classification, deterministic
research query generation, and refresh/backoff primitives. Search execution,
Reddit/YouTube content ingestion, LLM synthesis, document generation,
Notion/EFDS sync, and application submission remain intentionally unimplemented.
