# Playwright autofill

V10 runs Playwright locally against a user-selected application URL. It reads
only the verified local application packet and approved local form values. It
does not send field labels, values, files, screenshots, or logs to the shared
API.

Install/check Chromium with:

```bash
recruiting setup browser --install
recruiting local doctor
```

The default is visible Chromium (`headless = false`) so the user can intervene.
Chromium remains an external dependency of the packaged application.
