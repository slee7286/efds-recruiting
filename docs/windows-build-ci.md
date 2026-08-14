# Windows build CI

The repository has a packaging foundation and a V12 build workflow may build a
PyInstaller executable on a Windows runner. Chromium and MiKTeX remain external
dependencies; personal databases, browser profiles, credentials, and artifacts
must never be bundled. A produced executable must pass a fresh-data local
doctor/smoke test before it is described as a release.
