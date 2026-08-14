# V9 preimplementation review

## Reuse

- V8 `local_db.py`, `local_models.py`, `storage.py`, and `private_session_scope()`
  already provide the correct private-storage boundary.
- Existing public SQLAlchemy models and the PostgreSQL Alembic chain remain the
  shared intelligence source.
- The V6 review workspace, artifact services, AI workspace, backup/restore, and
  diagnostics are reusable local services.
- The existing CLI remains the compatibility surface; `recruiting` stays the
  preferred product command and `quant-recruiting` remains an alias.

## Generalize

- The V8 direct shared-session sync is generalized behind a transport-neutral
  client protocol.
- Shared snapshots become versioned API DTOs rather than serialized ORM rows.
- The existing review surface becomes the base of a broader localhost companion
  application with jobs, companies, AI, local-data, and settings views.

## Move behind API

- Normal end-user shared-intelligence reads and synchronization use the versioned
  `/api/v1` FastAPI service over HTTPS.
- Direct PostgreSQL access remains available only for developer/admin workflows,
  migration utilities, and tests.
- Brave Search and crawler credentials remain server-side.

## Desktop-packaging gap

- V8 is source-installable but does not yet produce a Windows installer or
  executable. V9 adds a PyInstaller spec, build command, and packaging
  documentation; a signed installer is deferred because signing credentials and
  a release CI environment are not available here.
- MiKTeX and Chromium remain external optional dependencies.

## Security gap

- The shared API exposes public intelligence DTOs only and has no private routes.
- The local app binds to loopback and validates the Host header. State-changing
  UI actions use a local CSRF token.
- OS-backed secret-store integration is provided as an extension point with a
  Windows DPAPI implementation when available; plaintext configuration is never
  used for database credentials.
- No telemetry or crash upload is introduced.

## Developer-only features

Direct PostgreSQL mode, shared research ingestion, migrations, and admin data
maintenance remain developer/admin capabilities. They are not needed by an
end-user local companion installation.

## End-user features

The local companion provides onboarding, local application/research views,
shared-cache browsing, AI task handoff, conversation search, privacy/data
diagnostics, backup/export controls, and offline status.

## Naming decision

The internal import package remains `quant_recruiting` for migration and import
compatibility. The product and CLI are presented as **Recruiting Assistant**;
`recruiting` is the preferred command and the old quant-oriented command remains
an alias.
