"""One-way shared-intelligence pull into the local SQLite cache."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

from quant_recruiting.config import Settings, get_settings
from quant_recruiting.db.models import (
    Application,
    Company,
    Job,
    ResearchClaim,
    ResearchDocument,
    ResearchSource,
)
from quant_recruiting.local_models import LocalSharedCache, LocalSyncCursor, LocalSyncState
from quant_recruiting.shared_client import get_shared_client
from quant_recruiting.storage import get_local_session

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017 - Python 3.10 compatibility


class Snapshot(BaseModel):
    id: str
    category: str
    updated_at: datetime | None = None
    content_hash: str
    provenance_ids: list[str] = []
    payload: dict[str, Any]


CompanySnapshot = Snapshot
JobSnapshot = Snapshot
FirmIntelligenceSnapshot = Snapshot
RecruitingCycleSnapshot = Snapshot
InterviewIntelligenceSnapshot = Snapshot
ResourceSnapshot = Snapshot


def _hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _datetime_value(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _snapshot(
    category: str, entity: Any, payload: dict[str, Any], updated_at: datetime | None
) -> Snapshot:
    return Snapshot(
        id=str(entity.id),
        category=category,
        updated_at=updated_at,
        content_hash=_hash(payload),
        provenance_ids=[str(value) for value in payload.get("source_ids", [])],
        payload=payload,
    )


def _company_snapshots(
    session: Any, company_slug: str | None, since: datetime | None
) -> list[Snapshot]:
    query = select(Company).order_by(Company.name)
    if company_slug:
        query = query.where(Company.slug == company_slug)
    if since:
        query = query.where(Company.updated_at > since)
    return [
        _snapshot(
            "companies",
            company,
            {"slug": company.slug, "name": company.name, "primary_domain": company.primary_domain},
            company.updated_at,
        )
        for company in session.scalars(query)
    ]


def _job_snapshots(session: Any, company_id: UUID | None, since: datetime | None) -> list[Snapshot]:
    query = select(Job).order_by(Job.date_last_seen.desc())
    if company_id:
        query = query.where(Job.company_id == company_id)
    if since:
        query = query.where(Job.updated_at > since)
    return [
        _snapshot(
            "jobs",
            job,
            {
                "company_id": str(job.company_id),
                "title": job.title,
                "role_family": job.role_family,
                "location_text": job.location_text,
                "job_url": job.job_url,
                "description_text": job.description_text,
                "requirements_text": job.requirements_text,
                "status": job.status,
                "internship_cycle": job.internship_cycle,
            },
            job.updated_at,
        )
        for job in session.scalars(query)
    ]


def _generic_snapshots(
    session: Any, category: str, model: Any, company_id: UUID | None
) -> list[Snapshot]:
    query = select(model)
    if company_id and hasattr(model, "company_id"):
        query = query.where(model.company_id == company_id)
    output = []
    for entity in session.scalars(query):
        payload = {
            column.name: getattr(entity, column.name)
            for column in model.__table__.columns
            if column.name not in {"id", "created_at", "updated_at"}
        }
        payload = json.loads(json.dumps(payload, default=str))
        output.append(
            _snapshot(category, entity, payload, getattr(entity, "updated_at", entity.created_at))
        )
    return output


def _upsert_cache(session: Any, snapshot: Snapshot, settings: Settings) -> bool:
    now = datetime.now(UTC)
    existing = session.get(LocalSharedCache, (snapshot.category, snapshot.id))
    changed = existing is None or existing.content_hash != snapshot.content_hash
    if existing is None:
        existing = LocalSharedCache(category=snapshot.category, shared_id=snapshot.id)
        session.add(existing)
    existing.payload = snapshot.payload
    existing.shared_updated_at = snapshot.updated_at
    existing.synced_at = now
    cadence = timedelta(hours=6 if snapshot.category == "jobs" else 24)
    existing.stale_after = now + cadence
    existing.source_server = (
        settings.shared_api_url
        if settings.shared_transport == "api"
        else "configured-shared-database"
    )
    existing.content_hash = snapshot.content_hash
    state = session.get(LocalSyncState, (snapshot.category, snapshot.id))
    if state is None:
        state = LocalSyncState(category=snapshot.category, shared_id=snapshot.id, synced_at=now)
        session.add(state)
    state.shared_updated_at = snapshot.updated_at
    state.synced_at = now
    state.stale_after = existing.stale_after
    state.source_server = existing.source_server
    state.content_hash = snapshot.content_hash
    state.status = "deleted" if snapshot.payload.get("_deleted") else "current"
    if snapshot.payload.get("_deleted"):
        if snapshot.category == "companies":
            company = session.get(Company, UUID(snapshot.id))
            if company is not None:
                company.active = False
        elif snapshot.category == "jobs":
            job = session.get(Job, UUID(snapshot.id))
            if job is not None:
                job.status = "archived"
        return changed
    if snapshot.category == "companies":
        company = session.get(Company, UUID(snapshot.id))
        if company is None:
            company = Company(
                id=UUID(snapshot.id), slug=snapshot.payload["slug"], name=snapshot.payload["name"]
            )
            session.add(company)
        company.slug = snapshot.payload["slug"]
        company.name = snapshot.payload["name"]
        company.primary_domain = snapshot.payload.get("primary_domain")
        company.metadata_ = {**(company.metadata_ or {}), "cache_origin": "shared"}
    elif snapshot.category == "jobs":
        job = session.get(Job, UUID(snapshot.id))
        if job is None:
            job = Job(
                id=UUID(snapshot.id),
                company_id=UUID(str(snapshot.payload["company_id"])),
                title=snapshot.payload["title"],
                role_family=snapshot.payload["role_family"],
                job_url=snapshot.payload["job_url"],
                source_type="shared_sync",
                date_first_seen=now,
                date_last_seen=now,
            )
            session.add(job)
        for field in (
            "company_id",
            "title",
            "role_family",
            "location_text",
            "job_url",
            "description_text",
            "requirements_text",
            "status",
            "internship_cycle",
        ):
            value = snapshot.payload.get(field)
            if field == "company_id" and value is not None:
                value = UUID(str(value))
            setattr(job, field, value)
        job.metadata_ = {**(job.metadata_ or {}), "cache_origin": "shared"}
    elif snapshot.category == "sources":
        source = session.get(ResearchSource, UUID(snapshot.id))
        payload = snapshot.payload
        if source is None:
            source = ResearchSource(
                id=UUID(snapshot.id),
                company_id=UUID(str(payload["company_id"])) if payload.get("company_id") else None,
                url=payload["url"],
                canonical_url=payload["canonical_url"],
                source_type=payload["source_type"],
                retrieved_at=_datetime_value(payload["retrieved_at"]) or now,
                content_hash=payload["content_hash"],
            )
            session.add(source)
        for field in (
            "company_id",
            "url",
            "canonical_url",
            "source_type",
            "title",
            "author",
            "publisher",
            "published_at",
            "retrieved_at",
            "observed_at",
            "content_hash",
            "raw_path",
            "normalized_path",
            "http_status",
            "language",
            "source_quality",
            "active",
        ):
            value = payload.get(field)
            if field in {"company_id"} and value:
                value = UUID(str(value))
            if field in {"published_at", "retrieved_at", "observed_at"}:
                value = _datetime_value(value)
            setattr(source, field, value)
        source.metadata_ = {**(source.metadata_ or {}), "cache_origin": "shared"}
    elif snapshot.category == "documents":
        document = session.get(ResearchDocument, UUID(snapshot.id))
        payload = snapshot.payload
        if document is None:
            document = ResearchDocument(
                id=UUID(snapshot.id),
                source_id=UUID(str(payload["source_id"])),
                company_id=UUID(str(payload["company_id"])) if payload.get("company_id") else None,
                document_type=payload["document_type"],
                title=payload["title"],
                content=payload["content"],
                content_hash=payload["content_hash"],
                version=payload["version"],
                generated_at=_datetime_value(payload["generated_at"]) or now,
            )
            session.add(document)
        document.metadata_ = {**(document.metadata_ or {}), "cache_origin": "shared"}
    elif snapshot.category == "claims":
        claim = session.get(ResearchClaim, UUID(snapshot.id))
        payload = snapshot.payload
        if claim is None:
            claim = ResearchClaim(
                id=UUID(snapshot.id),
                company_id=UUID(str(payload["company_id"])),
                source_id=UUID(str(payload["source_id"])),
                document_id=(
                    UUID(str(payload["document_id"])) if payload.get("document_id") else None
                ),
                claim=payload["claim"],
                claim_type=payload["claim_type"],
                confidence=payload["confidence"],
            )
            session.add(claim)
        claim.metadata_ = {**(claim.metadata_ or {}), "cache_origin": "shared"}
    return changed


def pull_shared(
    settings: Settings | None = None,
    *,
    company_slug: str | None = None,
    since: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    config = settings or get_settings()
    if config.offline_mode:
        return {"offline": True, "found": 0, "changed": 0, "categories": {}}
    client = get_shared_client(config)
    api_version = client.version()
    if api_version.api_version != "v1":
        raise RuntimeError(f"unsupported shared API version: {api_version.api_version}")
    effective_since = since
    if effective_since is None:
        with get_local_session(config) as local:
            cursor = local.get(LocalSyncCursor, config.shared_transport)
            if cursor and cursor.cursor:
                effective_since = datetime.fromisoformat(cursor.cursor)
            else:
                values = [row.shared_updated_at for row in local.scalars(select(LocalSyncState))]
                effective_since = max(
                    (value for value in values if value is not None), default=None
                )
    changes = client.changes(effective_since)
    snapshots = [
        Snapshot(
            id=change.entity_id,
            category=change.collection,
            updated_at=change.updated_at,
            content_hash=change.content_hash or _hash(change.payload or {}),
            payload=(change.payload or {})
            if change.operation == "upsert"
            else {"_deleted": True, "reason": change.reason},
        )
        for change in changes.changes
    ]
    if company_slug:
        company_ids = {
            item.id
            for item in snapshots
            if item.category == "companies" and item.payload.get("slug") == company_slug
        }
        if company_ids:
            snapshots = [
                item
                for item in snapshots
                if (
                    (item.category == "companies" and item.id in company_ids)
                    or str(item.payload.get("company_id")) in company_ids
                    or item.category
                    not in {
                        "companies",
                        "jobs",
                        "firm-intelligence",
                        "recruiting-cycles",
                        "sources",
                        "documents",
                        "claims",
                    }
                )
            ]
    if dry_run:
        return {
            "dry_run": True,
            "found": len(snapshots),
            "changed": None,
            "categories": _counts(snapshots),
        }
    changed = 0
    with get_local_session(config) as local:
        for snapshot in snapshots:
            changed += int(_upsert_cache(local, snapshot, config))
        latest = max((item.updated_at for item in snapshots if item.updated_at), default=None)
        if latest is not None:
            local.merge(
                LocalSyncCursor(
                    transport=config.shared_transport,
                    cursor=latest.isoformat(),
                    dataset_version=api_version.dataset_version,
                    updated_at=datetime.now(UTC),
                )
            )
    return {
        "dry_run": False,
        "found": len(snapshots),
        "changed": changed,
        "categories": _counts(snapshots),
    }


def _counts(snapshots: list[Snapshot]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for snapshot in snapshots:
        counts[snapshot.category] = counts.get(snapshot.category, 0) + 1
    return counts


def sync_status(settings: Settings | None = None) -> list[dict[str, Any]]:
    with get_local_session(settings) as session:
        rows = list(session.scalars(select(LocalSyncState).order_by(LocalSyncState.category)))
    now = datetime.now(UTC)

    def aware(value: datetime | None) -> datetime | None:
        return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value

    statuses = []
    for row in rows:
        stale = aware(row.stale_after)
        statuses.append(
            {
                "category": row.category,
                "synced_at": row.synced_at.isoformat(),
                "status": "stale" if stale is not None and stale < now else row.status,
                "object_id": row.shared_id,
            }
        )
    return statuses


def refresh_job_freshness(application_id: UUID, settings: Settings | None = None) -> dict[str, Any]:
    """Refresh the cached job before a local browser run when practical.

    This function only pulls public job/company intelligence. It never sends the
    application payload, email, candidate data, or browser state to the shared service.
    """
    config = settings or get_settings()
    now = datetime.now(UTC)
    with get_local_session(config) as local:
        application = local.get(Application, application_id)
        if application is None:
            raise ValueError("application not found locally")
        job_id = application.job_id
        job_status = application.job.status
        state = local.get(LocalSyncState, ("jobs", str(job_id)))
        stale_after = state.stale_after if state else None
        if stale_after is not None and stale_after.tzinfo is None:
            stale_after = stale_after.replace(tzinfo=UTC)
        stale = state is None or stale_after is None or stale_after < now
        company_slug = application.job.company.slug
    if not stale:
        return {"status": job_status, "stale": False, "refreshed": False, "offline": False}
    if config.offline_mode:
        return {"status": job_status, "stale": True, "refreshed": False, "offline": True}
    try:
        result = pull_shared(config, company_slug=company_slug)
    except Exception as exc:  # noqa: BLE001 - offline/network failures are surfaced as warnings.
        return {
            "status": job_status,
            "stale": True,
            "refreshed": False,
            "offline": False,
            "warning": str(exc),
        }
    with get_local_session(config) as local:
        refreshed_job = local.get(Job, job_id)
        refreshed_status = refreshed_job.status if refreshed_job else job_status
    return {
        "status": refreshed_status,
        "stale": True,
        "refreshed": True,
        "offline": False,
        "sync": result,
    }
