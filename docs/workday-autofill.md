# Workday autofill boundary

V12 detects Workday and supports conservative inspection plus common identity,
document, and navigation behavior through a provider-specific adapter wrapper.
It remains `PARTIAL` overall: authentication/account creation, résumé parser
mismatches, repeatable education/experience sections, and tenant-specific
controls pause for human review. The adapter is local-only and stops for
authentication, CAPTCHA, legal controls, unknown fields, and final submission.
