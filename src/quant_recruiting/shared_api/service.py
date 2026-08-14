"""Read-only shared intelligence API service functions."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from quant_recruiting.db.models import (
    Company,
    FirmIntelligenceItem,
    InterviewQuestion,
    Job,
    RecruitingCycle,
    Resource,
    SharedTombstone,
)
from quant_recruiting.shared_api.schemas import (
    CompanySnapshotV1,
    JobSnapshotV1,
    ProvenanceSummary,
    PublicRecordSnapshotV1,
)

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017 - Python 3.10 compatibility


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = int(base64.urlsafe_b64decode(padded.encode()).decode())
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise ValueError("invalid cursor") from exc
    if value < 0:
        raise ValueError("invalid cursor")
    return value


def content_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def provenance(payload: dict[str, Any]) -> ProvenanceSummary:
    values = payload.get("source_ids", [])
    ids = [str(value) for value in values] if isinstance(values, list) else []
    return ProvenanceSummary(source_ids=ids, source_count=len(ids))


def company_payload(company: Any) -> dict[str, Any]:
    return {
        "slug": company.slug,
        "name": company.name,
        "primary_domain": company.primary_domain,
        "careers_url": company.careers_url,
    }


def company_snapshot(company: Company) -> CompanySnapshotV1:
    payload = company_payload(company)
    return CompanySnapshotV1(
        id=company.id,
        version=company.updated_at.isoformat(),
        content_hash=content_hash(payload),
        updated_at=company.updated_at,
        **payload,
    )


def job_payload(job: Job) -> dict[str, Any]:
    return {
        "company_id": job.company_id,
        "title": job.title,
        "role_family": job.role_family,
        "location_text": job.location_text,
        "country": job.country,
        "city": job.city,
        "job_url": job.job_url,
        "description_text": job.description_text,
        "requirements_text": job.requirements_text,
        "status": job.status,
        "internship_cycle": job.internship_cycle,
        "application_deadline": job.application_deadline,
    }


def job_snapshot(job: Job) -> JobSnapshotV1:
    payload = job_payload(job)
    return JobSnapshotV1(
        id=job.id,
        version=job.updated_at.isoformat(),
        content_hash=content_hash(payload),
        updated_at=job.updated_at,
        **payload,
    )


def public_record(entity: Any, payload: dict[str, Any]) -> PublicRecordSnapshotV1:
    updated_at = getattr(entity, "updated_at", None) or getattr(entity, "created_at", None)
    if updated_at is None:
        updated_at = datetime.now(UTC)
    return PublicRecordSnapshotV1(
        id=entity.id,
        version=updated_at.isoformat(),
        content_hash=content_hash(payload),
        updated_at=updated_at,
        payload=payload,
        provenance=provenance(payload),
    )


def paginate_query(
    query: Select[Any], session: Session, *, limit: int, cursor: str | None
) -> tuple[list[Any], str | None]:
    bounded = min(max(limit, 1), 100)
    offset = decode_cursor(cursor)
    rows = list(session.scalars(query.offset(offset).limit(bounded + 1)))
    next_cursor = encode_cursor(offset + bounded) if len(rows) > bounded else None
    return rows[:bounded], next_cursor


def generic_payload(entity: Any) -> dict[str, Any]:
    return {
        column.name: getattr(entity, column.name)
        for column in entity.__table__.columns
        if column.name not in {"id", "created_at", "updated_at"}
    }


def collection_rows(session: Session, collection: str) -> list[tuple[Any, dict[str, Any]]]:
    model_by_collection: dict[str, Any] = {
        "firm-intelligence": FirmIntelligenceItem,
        "recruiting-cycles": RecruitingCycle,
        "interview-intelligence": InterviewQuestion,
        "resources": Resource,
    }
    model = model_by_collection[collection]
    return [(entity, generic_payload(entity)) for entity in session.scalars(select(model))]


def collection_updated_at(entity: Any) -> datetime:
    value = getattr(entity, "updated_at", None) or entity.created_at
    if not isinstance(value, datetime):
        raise TypeError("shared entity does not have a datetime timestamp")
    return value


def collection_hash(rows: list[tuple[Any, dict[str, Any]]]) -> str:
    return content_hash({str(entity.id): content_hash(payload) for entity, payload in rows})


def tombstone_rows(session: Session, since: datetime | None = None) -> list[SharedTombstone]:
    query = select(SharedTombstone).order_by(SharedTombstone.deleted_at, SharedTombstone.id)
    if since:
        query = query.where(SharedTombstone.deleted_at > since)
    return list(session.scalars(query))
