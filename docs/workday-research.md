# Workday research boundary

Workday tenants commonly use `myworkdayjobs.com` URLs and dynamic, often
React-backed application pages. Login, account creation, email verification,
résumé parsing, repeatable education/experience sections, and custom questions
vary by tenant.

V12 therefore classifies Workday detection and basic inspection as supported,
while repeaters, parser acceptance, and many custom controls remain
experimental or manual. The adapter may open a page, wait for the user to sign
in, inspect again, and proceed only with deterministic high-confidence fields.
It never creates accounts, stores passwords, follows verification links, or
clicks final submission.

After résumé upload, an ATS-produced value is an observation only. A mismatch
with the approved local candidate profile is persisted in
`browser_parsed_values` and requires human review.
