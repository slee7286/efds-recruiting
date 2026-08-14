"""Read-only FastAPI application for shared recruiting intelligence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from starlette.middleware.trustedhost import TrustedHostMiddleware

from quant_recruiting.config import Settings, get_settings
from quant_recruiting.db.models import (
    Company,
    FirmIntelligenceItem,
    InterviewQuestion,
    Job,
    RecruitingCycle,
    ResearchClaim,
    ResearchDocument,
    ResearchSource,
    Resource,
    ResourceRoleFamily,
    ResourceSkill,
    RoleFamily,
    Skill,
)
from quant_recruiting.shared_api.schemas import (
    ApiVersionV1,
    CollectionPageV1,
    CollectionVersionV1,
    CompanySnapshotV1,
    HealthV1,
    JobSnapshotV1,
    PublicRecordSnapshotV1,
    SyncChangesV1,
    SyncChangeV1,
    SyncManifestV1,
)
from quant_recruiting.shared_api.service import (
    collection_hash,
    collection_updated_at,
    company_payload,
    company_snapshot,
    content_hash,
    generic_payload,
    job_payload,
    job_snapshot,
    paginate_query,
    public_record,
    tombstone_rows,
)
from quant_recruiting.storage import get_shared_session

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017 - Python 3.10 compatibility


def _page(items: list[Any], next_cursor: str | None, limit: int) -> CollectionPageV1:
    return CollectionPageV1(items=items, next_cursor=next_cursor, limit=min(max(limit, 1), 100))


def _updated_since(query: Any, column: Any, value: datetime | None) -> Any:
    return query.where(column > value) if value else query


def _record_page(
    session: Any, collection: str, query: Any, *, limit: int, cursor: str | None
) -> CollectionPageV1:
    rows, next_cursor = paginate_query(query, session, limit=limit, cursor=cursor)
    return _page([public_record(row, generic_payload(row)) for row in rows], next_cursor, limit)


def create_shared_api(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    docs_url = "/docs" if config.api_docs_enabled else None
    app = FastAPI(
        title="Recruiting Intelligence Shared API",
        version="0.3.0",
        docs_url=docs_url,
        redoc_url="/redoc" if config.api_docs_enabled else None,
        openapi_url="/openapi.json" if config.api_docs_enabled else None,
    )
    allowed_hosts = list(config.api_allowed_hosts)
    if config.api_environment == "test":
        allowed_hosts.append("testserver")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    if config.api_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.api_allowed_origins,
            allow_methods=["GET"],
            allow_headers=["Accept", "If-None-Match"],
        )

    @app.get("/api/v1/health", response_model=HealthV1)
    def health() -> HealthV1:
        try:
            with get_shared_session(config) as session:
                session.execute(select(Company).limit(1))
            return HealthV1(status="ok", database="reachable", schema_compatible=True)
        except Exception:
            return HealthV1(status="degraded", database="unreachable", schema_compatible=False)

    @app.get("/api/v1/version", response_model=ApiVersionV1)
    def version() -> ApiVersionV1:
        return ApiVersionV1(dataset_version=_manifest(config).dataset_version)

    @app.get("/api/v1/companies", response_model=CollectionPageV1)
    def companies(
        query: str | None = None,
        updated_since: datetime | None = None,
        limit: int = Query(50, ge=1, le=100),
        cursor: str | None = None,
    ) -> CollectionPageV1:
        with get_shared_session(config) as session:
            statement = select(Company).order_by(Company.updated_at, Company.id)
            if query:
                pattern = f"%{query}%"
                statement = statement.where(
                    Company.name.ilike(pattern) | Company.slug.ilike(pattern)
                )
            statement = _updated_since(statement, Company.updated_at, updated_since)
            rows, next_cursor = paginate_query(statement, session, limit=limit, cursor=cursor)
            return _page([company_snapshot(row) for row in rows], next_cursor, limit)

    @app.get("/api/v1/companies/{company_id}", response_model=CompanySnapshotV1)
    def company(company_id: UUID) -> CompanySnapshotV1:
        with get_shared_session(config) as session:
            row = session.get(Company, company_id)
            if row is None:
                raise HTTPException(status_code=404, detail="company not found")
            return company_snapshot(row)

    @app.get("/api/v1/jobs", response_model=CollectionPageV1)
    def jobs(
        company_id: UUID | None = None,
        role_family: str | None = None,
        location: str | None = None,
        cycle: str | None = None,
        status: str | None = None,
        updated_since: datetime | None = None,
        limit: int = Query(50, ge=1, le=100),
        cursor: str | None = None,
    ) -> CollectionPageV1:
        with get_shared_session(config) as session:
            statement = select(Job).order_by(Job.updated_at, Job.id)
            if company_id:
                statement = statement.where(Job.company_id == company_id)
            if role_family:
                statement = statement.where(Job.role_family == role_family)
            if location:
                statement = statement.where(Job.location_text.ilike(f"%{location}%"))
            if cycle:
                statement = statement.where(Job.internship_cycle == cycle)
            if status:
                statement = statement.where(Job.status == status)
            statement = _updated_since(statement, Job.updated_at, updated_since)
            rows, next_cursor = paginate_query(statement, session, limit=limit, cursor=cursor)
            return _page([job_snapshot(row) for row in rows], next_cursor, limit)

    @app.get("/api/v1/jobs/{job_id}", response_model=JobSnapshotV1)
    def job(job_id: UUID) -> JobSnapshotV1:
        with get_shared_session(config) as session:
            row = session.get(Job, job_id)
            if row is None:
                raise HTTPException(status_code=404, detail="job not found")
            return job_snapshot(row)

    @app.get("/api/v1/companies/{company_id}/intelligence", response_model=CollectionPageV1)
    def company_intelligence(
        company_id: UUID,
        limit: int = Query(50, ge=1, le=100),
        cursor: str | None = None,
    ) -> CollectionPageV1:
        with get_shared_session(config) as session:
            query = (
                select(FirmIntelligenceItem)
                .where(FirmIntelligenceItem.company_id == company_id)
                .order_by(FirmIntelligenceItem.updated_at, FirmIntelligenceItem.id)
            )
            return _record_page(session, "firm-intelligence", query, limit=limit, cursor=cursor)

    @app.get("/api/v1/companies/{company_id}/recruiting", response_model=CollectionPageV1)
    def company_recruiting(
        company_id: UUID,
        limit: int = Query(50, ge=1, le=100),
        cursor: str | None = None,
    ) -> CollectionPageV1:
        with get_shared_session(config) as session:
            query = (
                select(RecruitingCycle)
                .where(RecruitingCycle.company_id == company_id)
                .order_by(RecruitingCycle.updated_at, RecruitingCycle.id)
            )
            return _record_page(session, "recruiting-cycles", query, limit=limit, cursor=cursor)

    @app.get("/api/v1/companies/{company_id}/interviews", response_model=CollectionPageV1)
    def company_interviews(
        company_id: UUID,
        limit: int = Query(50, ge=1, le=100),
        cursor: str | None = None,
    ) -> CollectionPageV1:
        with get_shared_session(config) as session:
            query = (
                select(InterviewQuestion)
                .where(InterviewQuestion.company_id == company_id)
                .order_by(InterviewQuestion.created_at, InterviewQuestion.id)
            )
            return _record_page(
                session, "interview-intelligence", query, limit=limit, cursor=cursor
            )

    @app.get("/api/v1/resources", response_model=CollectionPageV1)
    def resources(
        skill: str | None = None,
        role_family: str | None = None,
        resource_type: str | None = None,
        updated_since: datetime | None = None,
        limit: int = Query(50, ge=1, le=100),
        cursor: str | None = None,
    ) -> CollectionPageV1:
        with get_shared_session(config) as session:
            statement = select(Resource).order_by(Resource.updated_at, Resource.id)
            if resource_type:
                statement = statement.where(Resource.resource_type == resource_type)
            if skill:
                statement = statement.join(ResourceSkill).join(Skill).where(Skill.slug == skill)
            if role_family:
                statement = (
                    statement.join(ResourceRoleFamily)
                    .join(RoleFamily)
                    .where(RoleFamily.slug == role_family)
                )
            statement = _updated_since(statement, Resource.updated_at, updated_since)
            return _record_page(session, "resources", statement, limit=limit, cursor=cursor)

    @app.get("/api/v1/resources/{resource_id}", response_model=PublicRecordSnapshotV1)
    def resource(resource_id: UUID) -> PublicRecordSnapshotV1:
        with get_shared_session(config) as session:
            row = session.get(Resource, resource_id)
            if row is None:
                raise HTTPException(status_code=404, detail="resource not found")
            return public_record(row, generic_payload(row))

    @app.get("/api/v1/sync/manifest", response_model=SyncManifestV1)
    def manifest(request: Request, response: Response) -> SyncManifestV1 | Response:
        result = _manifest(config)
        etag = f'"{result.dataset_version}"'
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = "public, max-age=300"
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return result

    @app.get("/api/v1/sync/changes", response_model=SyncChangesV1)
    def changes(
        since: datetime | None = None,
        limit: int = Query(100, ge=1, le=500),
    ) -> SyncChangesV1:
        with get_shared_session(config) as session:
            return _changes_from_session(session, since=since, limit=limit)

    return app


def _manifest(settings: Settings) -> SyncManifestV1:
    with get_shared_session(settings) as session:
        collections: dict[str, Any] = {}
        all_values: list[str] = []
        for name, model in (
            ("companies", Company),
            ("jobs", Job),
            ("firm-intelligence", FirmIntelligenceItem),
            ("recruiting-cycles", RecruitingCycle),
            ("interview-intelligence", InterviewQuestion),
            ("resources", Resource),
            ("sources", ResearchSource),
            ("documents", ResearchDocument),
            ("claims", ResearchClaim),
        ):
            rows = [(row, generic_payload(row)) for row in session.scalars(select(model))]
            if name == "companies":
                rows = [(row, {**generic_payload(row), **company_payload(row)}) for row, _ in rows]
            latest = max((collection_updated_at(row) for row, _ in rows), default=None)
            version = collection_hash(rows)
            collections[name] = {"version": version, "item_count": len(rows), "updated_at": latest}
            all_values.append(version)
        dataset_version = content_hash({"collections": all_values})
    return SyncManifestV1(
        dataset_version=dataset_version,
        generated_at=datetime.now(UTC),
        collections={name: CollectionVersionV1(**value) for name, value in collections.items()},
    )


def _changes_from_session(
    session: Any, *, since: datetime | None = None, limit: int = 500
) -> SyncChangesV1:
    records: list[SyncChangeV1] = []
    models = (
        ("companies", Company),
        ("jobs", Job),
        ("firm-intelligence", FirmIntelligenceItem),
        ("recruiting-cycles", RecruitingCycle),
        ("interview-intelligence", InterviewQuestion),
        ("resources", Resource),
        ("sources", ResearchSource),
        ("documents", ResearchDocument),
        ("claims", ResearchClaim),
    )
    for collection, model in models:
        timestamp_column = getattr(model, "updated_at", model.created_at)
        query = select(model).order_by(timestamp_column, model.id)
        if since:
            query = query.where(timestamp_column > since)
        for row in session.scalars(query.limit(limit)):
            payload = generic_payload(row)
            if collection == "companies":
                payload = company_payload(row)
            elif collection == "jobs":
                payload = job_payload(row)
            payload = json.loads(json.dumps(payload, default=str))
            updated_at = collection_updated_at(row)
            records.append(
                SyncChangeV1(
                    collection=collection,
                    operation="upsert",
                    entity_id=str(row.id),
                    version=updated_at.isoformat(),
                    updated_at=updated_at,
                    content_hash=content_hash(payload),
                    payload=payload,
                )
            )
    for row in tombstone_rows(session, since):
        records.append(
            SyncChangeV1(
                collection=row.collection,
                operation="delete",
                entity_id=row.entity_id,
                version=row.deleted_at.isoformat(),
                updated_at=row.deleted_at,
                reason=row.reason,
            )
        )
    records.sort(key=lambda item: (item.updated_at, item.entity_id))
    return SyncChangesV1(changes=records[: min(max(limit, 1), 500)], next_cursor=None)
