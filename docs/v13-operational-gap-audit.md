# V13 operational gap audit

Date: 2026-08-14

This audit is based on the V12 source tree, fixture tests, and the verification
available in the current Windows environment. “Live verified” is used only when
the capability was exercised against its real dependency; a local fixture or a
mock is explicitly labelled otherwise.

| Capability | Classification | Evidence / gap |
|---|---|---|
| Shared HTTP API | IMPLEMENTED_FIXTURE_VERIFIED | FastAPI contract and privacy tests exist; no reachable deployment was available for this audit. |
| Shared PostgreSQL | BLOCKED_BY_ENVIRONMENT | The configured Supabase hostname failed DNS resolution; no live read/write claim is made. |
| Gmail OAuth | IMPLEMENTED_NOT_LIVE_VERIFIED | Provider boundary and read-only scope exist; local OAuth/token lifecycle is a V13 implementation target. |
| Gmail incremental sync | IMPLEMENTED_NOT_LIVE_VERIFIED | Local cursor fields and fixture ingestion exist; real Gmail history-ID sync is not yet verified. |
| Greenhouse | IMPLEMENTED_FIXTURE_VERIFIED | Adapter, deterministic mapping, upload and no-submit fixtures are present; real page validation is pending. |
| Lever | IMPLEMENTED_FIXTURE_VERIFIED | Adapter and generic form regression coverage exist; real page validation is pending. |
| Ashby | IMPLEMENTED_FIXTURE_VERIFIED | Adapter and dynamic-form fixture coverage exist; real page validation is pending. |
| Workday | PARTIAL | Detection, assisted-mode foundations and parser-value storage exist; repeaters and parser behavior require real sanitized fixtures. |
| SmartRecruiters | PARTIAL | Detection/wrapper capability exists; production behavior is not live-verified. |
| iCIMS | EXPERIMENTAL | Detection and conservative wrapper exist; iframe/session behavior is not live-verified. |
| Workable/BambooHR | DETECTED_ONLY / PARTIAL | Detection metadata exists; no reliable broad autofill claim is made. |
| SuccessFactors/Taleo | DETECTED_ONLY | Capability metadata and conservative detection only. |
| Generic forms | IMPLEMENTED_FIXTURE_VERIFIED | Conservative field mapping and no-submit fixtures exist; arbitrary JavaScript forms remain out of scope. |
| Browser restart/resume | IMPLEMENTED_FIXTURE_VERIFIED | Attempt/checkpoint persistence and restart tests exist; real ATS interruption testing is pending. |
| Browser diagnostics | IMPLEMENTED_FIXTURE_VERIFIED | Sanitized bundle, hashes and privacy checks exist; real failure captures are pending. |
| Windows Task Scheduler | IMPLEMENTED_NOT_LIVE_VERIFIED | XML generation and Windows code exist; this environment could not install `schtasks`. |
| Windows package build | IMPLEMENTED_NOT_LIVE_VERIFIED | GitHub Actions workflow/spec exist; PyInstaller is not installed locally and no built executable was run. |
| Packaged application startup | BLOCKED_BY_ENVIRONMENT | Requires a produced Windows executable. |
| Packaged Playwright operation | BLOCKED_BY_ENVIRONMENT | Requires the packaged executable and external Chromium. |
| Packaged MiKTeX detection | BLOCKED_BY_ENVIRONMENT | Requires packaged smoke execution; source-level detection exists. |
| Local notifications | IMPLEMENTED_FIXTURE_VERIFIED | Local notification persistence and dashboard fallback are covered; Windows toast delivery is environment-dependent. |
| Background runner | IMPLEMENTED_FIXTURE_VERIFIED | Single-run lock, local results, reminder/alert handling and offline behavior are tested. |

## Highest-value V13 work

1. Make Gmail OAuth and incremental history synchronization real while keeping
   tokens and message content local.
2. Make ATS capability reports evidence-backed and turn sanitized real failures
   into regression fixtures.
3. Improve diagnostics, dogfood metrics and local readiness reporting.
4. Re-attempt live API/PostgreSQL, Task Scheduler and Windows packaging only
   where the environment permits it.

The repository does not currently justify a claim of real-world production ATS
coverage or a completed Windows release. V13 should make those boundaries
visible rather than hide them behind optimistic capability labels.
