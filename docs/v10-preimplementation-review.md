# V10 pre-implementation review

## Scope

V9 already has a local-first application packet, a local SQLite database, a
loopback companion, and reserved `browser_fill_runs`/
`browser_field_mappings` tables. V10 extends those contracts into a local-only
Playwright workflow. The shared API remains read-only public intelligence and
is not involved in browser field capture or filling.

## Existing browser-related code

| Area | Classification | Finding |
| --- | --- | --- |
| `application_form_payload.json` | REUSE | Canonical, approved local input for V10. |
| Packet verification and artifact hashes | REUSE | Preflight must require a current verified packet. |
| Candidate profile and sensitive fields | EXTEND | Reusable values exist; form-specific values and explicit approval need a local boundary. |
| `browser_fill_runs` and `browser_field_mappings` | EXTEND | Historical V6 reservations remain compatible; richer V10 records use local-only tables so private browser telemetry is not added to the shared schema. |
| Local SQLite bootstrap | EXTEND | Add browser run/page/field/attempt/upload/error/alias tables and a local schema bump. |
| Companion UI | EXTEND | Add browser status, unresolved-field, and checklist links to application pages. |
| CLI setup check | EXTEND | Replace package-only reporting with Playwright and Chromium diagnostics/install guidance. |
| ATS metadata | REUSE | Existing Greenhouse/Lever/Ashby company ATS records inform detection but never override DOM evidence. |
| V9 package/build | EXTEND | Playwright Chromium remains an external local dependency. |

## Deliberate safety decisions

- Browser records are local-only and are never sent to the shared API.
- Preflight refuses missing/stale/unapproved packets.
- Exact/high-confidence mappings may fill; medium/low/unknown mappings pause.
- Sensitive, legal, consent, CAPTCHA, authentication, and final-submit controls
  always require a human.
- The Playwright service has no submit operation. A dedicated
  `HumanSubmissionRequired` exception guards final-submit controls.
- The first implementation uses conservative DOM inspection and explicit ATS
  selectors/aliases. It does not attempt to defeat anti-bot systems or infer
  applicant information.

## V10 gaps to close

1. Local browser lifecycle and audit models.
2. Deterministic field taxonomy, aliases, mapping, and verification.
3. Greenhouse, Lever, Ashby, and conservative generic adapters.
4. Multi-step inspection, manual resolution, resume, and final-review state.
5. Fake-ATS fixtures proving zero automatic submissions.
6. Local companion and CLI integration plus V10 documentation.
