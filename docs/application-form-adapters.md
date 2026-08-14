# Application form adapters

V12 includes conservative Greenhouse, Lever, Ashby, Workday, SmartRecruiters,
iCIMS, Workable, BambooHR, SuccessFactors, Taleo, and generic HTML adapters.
Adapters share inspection, deterministic mapping, filling, verification, and
navigation contracts. Provider-specific detection is based on public host/DOM
signals; it is not authenticated scraping or anti-bot circumvention.

Capability levels are exposed by `recruiting browser ats-status`. Workday and
iCIMS are partial/experimental outside proven common fields; Taleo is detection
only until tenant fixtures prove safe filling. Custom frameworks remain an
extension point, not claimed coverage.
