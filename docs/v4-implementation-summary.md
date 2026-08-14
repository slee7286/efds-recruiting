# V4 implementation summary

V4 adds an executable Brave search-provider path, search usage budgets, a scored
fetch queue, immutable raw artifacts, PDF normalization with page markers,
public discussion/video/GitHub normalizers, deterministic interview extraction,
topic tagging, resource normalization/sections, coverage/preparation reports,
and richer dossier/AI manifests. Existing V1–V3 source identity, migrations,
ATS adapters, and CLI compatibility remain intact.

Provider credentials were not assumed. Live PostgreSQL/Supabase verification is
reported separately and is only claimed when configured in the environment.
