# Browser diagnostics

`recruiting browser diagnostics <run-id>` creates a local bundle containing
run metadata, ATS detection reasons, form snapshot, mapping hashes, validation,
and conservative console/network placeholders. `browser export-diagnostics`
exports that JSON/HTML bundle without screenshots by default.

`browser privacy-check` is a heuristic scan for literal email addresses. It is
not perfect redaction; screenshots must still be reviewed before sharing.
Request bodies, cookies, authorization headers, and browser profiles are never
included in the default diagnostic bundle.
