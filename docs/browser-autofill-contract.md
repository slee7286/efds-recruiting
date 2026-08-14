# Browser autofill contract

V10 implements the local browser contract using `browser_runs`,
`browser_pages`, `browser_fields`, local mappings, attempts, uploads, and
validation errors. The older `browser_fill_runs` and `browser_field_mappings`
tables remain compatibility reservations. V10 records field labels/types,
source IDs, expected/actual hashes, status, timestamps, and local screenshots.

Automation stops before final submission, never guesses sensitive answers, and
never bypasses CAPTCHA, authentication, robots, rate limits, or access controls.
