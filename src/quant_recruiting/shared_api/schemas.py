"""Stable public API contracts independent of the ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ProvenanceSummary(BaseModel):
    source_ids: list[str] = Field(default_factory=list)
    source_count: int = 0


class CompanySnapshotV1(BaseModel):
    id: UUID
    version: str
    content_hash: str
    updated_at: datetime
    slug: str
    name: str
    primary_domain: str | None = None
    careers_url: str | None = None
    provenance: ProvenanceSummary = Field(default_factory=ProvenanceSummary)


class JobSnapshotV1(BaseModel):
    id: UUID
    version: str
    content_hash: str
    updated_at: datetime
    company_id: UUID
    title: str
    role_family: str
    location_text: str | None = None
    country: str | None = None
    city: str | None = None
    job_url: str
    description_text: str | None = None
    requirements_text: str | None = None
    status: str
    internship_cycle: str | None = None
    application_deadline: datetime | None = None
    provenance: ProvenanceSummary = Field(default_factory=ProvenanceSummary)


class PublicRecordSnapshotV1(BaseModel):
    id: UUID
    version: str
    content_hash: str
    updated_at: datetime
    payload: dict[str, Any]
    provenance: ProvenanceSummary = Field(default_factory=ProvenanceSummary)


class CollectionPageV1(BaseModel):
    items: list[Any]
    next_cursor: str | None = None
    limit: int


class CollectionVersionV1(BaseModel):
    version: str
    item_count: int
    updated_at: datetime | None = None


class SyncManifestV1(BaseModel):
    schema_version: int = 1
    dataset_version: str
    generated_at: datetime
    collections: dict[str, CollectionVersionV1]


class SyncChangeV1(BaseModel):
    collection: str
    operation: Literal["upsert", "delete"]
    entity_id: str
    version: str
    updated_at: datetime
    content_hash: str | None = None
    payload: dict[str, Any] | None = None
    reason: str | None = None


class SyncChangesV1(BaseModel):
    schema_version: int = 1
    changes: list[SyncChangeV1]
    next_cursor: str | None = None


class ApiVersionV1(BaseModel):
    api_version: str = "v1"
    client_minimum: str = "0.3.0"
    client_latest: str = "0.3.0"
    dataset_version: str
    schema_version: int = 1


class HealthV1(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["reachable", "unreachable"]
    schema_compatible: bool
