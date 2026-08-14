# V10 implementation summary

V10 adds local Playwright browser runs, packet preflight, deterministic form
inspection/mapping, Greenhouse/Lever/Ashby/generic adapters, local field-value
overrides, exact answer/document verification, screenshots and review files,
resume/status/abort/resolve commands, and a hard human final-submit gate.

No browser data is sent to shared Postgres/API. No CAPTCHA, authentication,
anti-bot bypass, or automatic submission is implemented. Workday and other
unlisted ATS providers remain extension points.
