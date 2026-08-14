# ATS capabilities

Run `recruiting browser ats-status` to view the current registry. Detection is
separate from autofill support:

- `SUPPORTED`: fixture-backed behavior is suitable for normal use within the
  documented boundary.
- `PARTIAL`: common fields work but provider/tenant variation may pause.
- `EXPERIMENTAL`: inspect and assisted workflows are preferred.
- `DETECTED_ONLY`: the provider is recognized but filling is not claimed.
- `UNSUPPORTED`: no safe adapter is available.

V12 includes registry entries for Greenhouse, Lever, Ashby, Workday,
SmartRecruiters, iCIMS, Workable, BambooHR, SuccessFactors, Taleo, and generic
HTML. Workday and iCIMS are intentionally not described as fully supported.
