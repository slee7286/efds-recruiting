# V13 dogfooding

Use headed, supervised browser runs against a real application only when the
user genuinely intends to complete it. Inspect-only mode and sanitized fixture
capture are preferred for adapter work.

```text
recruiting browser run <application-id> --mode inspect --dogfood
recruiting browser diagnostics <run-id>
recruiting browser dogfood-report
```

Dogfood data is local. It records adapter, status, failure categories and
manual-intervention counts, not raw candidate values. A real failure should
become a sanitized fixture, a regression test, and an adapter change before
being treated as fixed.

The final-submit gate remains mandatory: automation stops before the final
application submission control.
