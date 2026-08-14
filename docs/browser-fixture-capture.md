# Browser fixture capture

`recruiting browser capture-fixture <url>` is an inspect-only developer tool. It
opens a page, detects the ATS, saves a form snapshot, and sanitizes the DOM
before writing a local fixture under `cache/ats-fixtures/`.

It does not fill, submit, retain passwords, or export cookies/tokens. Captured
fixtures are not automatically added to tests. A developer must review the
sanitized output and manually promote a safe fixture to
`tests/fixtures/ats/<provider>/`.
