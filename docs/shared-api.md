# Shared intelligence API

V9 adds a versioned read-only FastAPI service under `/api/v1`. It exposes
public companies, jobs, firm intelligence, recruiting cycles, interview
evidence, resources, health/version information, and incremental sync data.
SQLAlchemy models are never serialized directly; Pydantic DTOs are the public
contract. Admin ingestion and database migrations remain outside this API.

Run the development server with `recruiting api serve`. The backend uses direct
PostgreSQL internally, while clients use `SHARED_TRANSPORT=api` and
`SHARED_API_URL`. Production API docs can be disabled with `API_DOCS_ENABLED=false`.
