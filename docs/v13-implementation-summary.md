# V13 implementation summary

V13 hardens operations without adding a new product domain.

Implemented locally:

- official Gmail installed-app OAuth scaffolding with loopback state validation,
  OS-backed refresh-token storage, read-only scope, bounded bootstrap search and
  Gmail history-ID incremental synchronization;
- explicit sanitized recruiting-email fixture capture;
- additive local schema v5 fields for Gmail cursors, browser dogfood metadata
  and private browser issues;
- evidence-shaped ATS capability reporting with fixture and real-sanitized
  fixture counts;
- dogfood mode/reporting, operational readiness checks and cloud-sync path
  warnings;
- local-only diagnostics/privacy behavior remains in force.

The current environment has Playwright, Chromium and MiKTeX available. Google
OAuth libraries are declared in the project and lockfile but no Gmail OAuth
credentials were available for a live account test. The configured Supabase
hostname was not resolvable, and Task Scheduler/PyInstaller could not be
validated from this environment. No live ATS page was used as evidence.

The mandatory no-submit gate and local-only personal-data invariant remain
unchanged.
