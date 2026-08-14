# Windows packaging

V9 provides a PyInstaller spec at
`packaging/recruiting_assistant.spec` and `scripts/build_windows.ps1` for a
Windows x64 build. Templates, prompts, and config fixtures are bundled; the
private database, artifacts, browser profiles, and credentials are not.

The release build should be made in CI or a Windows environment with PyInstaller
installed. MiKTeX/pdflatex and Playwright Chromium remain external optional
dependencies. A signed installer and auto-update channel require release
signing infrastructure and are intentionally deferred.
