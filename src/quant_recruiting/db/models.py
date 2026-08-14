from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from quant_recruiting.db.base import (
    Base,
    CreatedAtMixin,
    UpdatedAtMixin,
    UUIDPrimaryKeyMixin,
)

JSONB = JSON
PGUUID = Uuid


class Company(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "companies"
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    primary_domain: Mapped[str | None] = mapped_column(String(255))
    careers_url: Mapped[str | None] = mapped_column(Text)
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    headquarters: Mapped[str | None] = mapped_column(String(255))
    company_type: Mapped[str | None] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    normalized_name: Mapped[str | None] = mapped_column(String(255), index=True)
    aliases: Mapped[list[CompanyAlias]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    domains: Mapped[list[CompanyDomain]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    jobs: Mapped[list[Job]] = relationship(back_populates="company")
    sources: Mapped[list[ResearchSource]] = relationship(back_populates="company")
    discovered_urls: Mapped[list[DiscoveredURL]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    role_families: Mapped[list[RoleFamily]] = relationship(back_populates="company")
    ats_configurations: Mapped[list[CompanyATS]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    intelligence_items: Mapped[list[FirmIntelligenceItem]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    resources: Mapped[list[ResourceCompany]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class CompanyAlias(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "company_aliases"
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(255), nullable=False)
    source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_sources.id", ondelete="SET NULL")
    )
    company: Mapped[Company] = relationship(back_populates="aliases")
    source: Mapped[ResearchSource | None] = relationship(foreign_keys=[source_id])
    __table_args__ = (UniqueConstraint("company_id", "normalized_alias"),)


class CompanyDomain(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "company_domains"
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    domain_type: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    canonical: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_sources.id", ondelete="SET NULL")
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    company: Mapped[Company] = relationship(back_populates="domains")
    source: Mapped[ResearchSource | None] = relationship(foreign_keys=[source_id])
    __table_args__ = (
        UniqueConstraint("company_id", "domain"),
        CheckConstraint(
            "domain_type IN ("
            "'corporate','careers','trading','research','technology','blog','other')",
            name="domain_type_values",
        ),
    )


class RoleFamily(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "role_families"
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("role_families.id", ondelete="SET NULL")
    )
    company_id: Mapped[UUID | None] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    parent: Mapped[RoleFamily | None] = relationship(
        remote_side="RoleFamily.id", back_populates="children"
    )
    children: Mapped[list[RoleFamily]] = relationship(back_populates="parent")
    company: Mapped[Company | None] = relationship(back_populates="role_families")
    jobs: Mapped[list[Job]] = relationship(back_populates="role_family_ref")


class CompanyATS(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "company_ats"
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    board_identifier: Mapped[str | None] = mapped_column(String(255))
    board_url: Mapped[str] = mapped_column(Text, nullable=False)
    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_sources.id", ondelete="SET NULL")
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    company: Mapped[Company] = relationship(back_populates="ats_configurations")
    source: Mapped[ResearchSource | None] = relationship(foreign_keys=[source_id])
    jobs: Mapped[list[Job]] = relationship(back_populates="ats")
    __table_args__ = (
        UniqueConstraint("company_id", "provider", "board_identifier"),
        CheckConstraint(
            "provider IN ('greenhouse','lever','ashby','other')", name="provider_values"
        ),
    )


class Job(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "jobs"
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    role_family_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("role_families.id", ondelete="SET NULL")
    )
    company_ats_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("company_ats.id", ondelete="SET NULL")
    )
    external_id: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(255))
    role_family: Mapped[str] = mapped_column(String(80), nullable=False)
    employment_type: Mapped[str | None] = mapped_column(String(80))
    internship_cycle: Mapped[str | None] = mapped_column(String(40))
    location_text: Mapped[str | None] = mapped_column(String(500))
    country: Mapped[str | None] = mapped_column(String(120))
    city: Mapped[str | None] = mapped_column(String(120))
    remote_policy: Mapped[str | None] = mapped_column(String(80))
    job_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    description_text: Mapped[str | None] = mapped_column(Text)
    requirements_text: Mapped[str | None] = mapped_column(Text)
    date_posted: Mapped[date | None] = mapped_column(Date)
    date_first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    date_last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    application_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="discovered", server_default="discovered"
    )
    content_hash: Mapped[str | None] = mapped_column(String(64))
    classification_confidence: Mapped[float | None] = mapped_column(Float)
    classification_method: Mapped[str | None] = mapped_column(String(40))
    classification_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    company: Mapped[Company] = relationship(back_populates="jobs")
    role_family_ref: Mapped[RoleFamily | None] = relationship(back_populates="jobs")
    ats: Mapped[CompanyATS | None] = relationship(back_populates="jobs")
    applications: Mapped[list[Application]] = relationship(back_populates="job")
    observations: Mapped[list[JobObservation]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    skills: Mapped[list[JobSkill]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    __table_args__ = (
        CheckConstraint(
            "status IN ('discovered','open','closed','archived')", name="status_values"
        ),
        Index(
            "uq_jobs_company_external_id",
            "company_id",
            "external_id",
            unique=True,
            postgresql_where="external_id IS NOT NULL",
        ),
        Index("uq_jobs_company_url", "company_id", "job_url", unique=True),
        CheckConstraint(
            "classification_confidence IS NULL OR "
            "(classification_confidence >= 0 AND classification_confidence <= 1)",
            name="classification_confidence_range",
        ),
    )


class JobObservation(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "job_observations"
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description_text: Mapped[str | None] = mapped_column(Text)
    requirements_text: Mapped[str | None] = mapped_column(Text)
    application_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    structured_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    job: Mapped[Job] = relationship(back_populates="observations")
    __table_args__ = (Index("ix_job_observations_job_observed_at", "job_id", "observed_at"),)


class DiscoveredURL(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "discovered_urls"
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    discovery_method: Mapped[str] = mapped_column(String(80), nullable=False)
    probable_source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False)
    discovery_reason: Mapped[str] = mapped_column(Text, nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="discovered")
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_sources.id", ondelete="SET NULL")
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    last_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    company: Mapped[Company] = relationship(back_populates="discovered_urls")
    ingested_source: Mapped[ResearchSource | None] = relationship(foreign_keys=[ingested_source_id])
    __table_args__ = (
        UniqueConstraint("company_id", "canonical_url"),
        CheckConstraint(
            "status IN ('discovered','queued','ingested','ignored','failed')",
            name="status_values",
        ),
        CheckConstraint(
            "relevance_score >= 0 AND relevance_score <= 1", name="relevance_score_range"
        ),
    )


class Application(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "applications"
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="discovered", server_default="discovered"
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    fit_score: Mapped[float | None] = mapped_column(Float)
    desirability_score: Mapped[float | None] = mapped_column(Float)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    application_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_action: Mapped[str | None] = mapped_column(Text)
    next_action_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    application_url: Mapped[str | None] = mapped_column(Text)
    cover_letter_requirement: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unknown", server_default="unknown"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    job: Mapped[Job] = relationship(back_populates="applications")
    events: Mapped[list[ApplicationEvent]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    cv_versions: Mapped[list[CVVersion]] = relationship(back_populates="application")
    questions: Mapped[list[ApplicationQuestion]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'discovered','shortlisted','preparing','ready_for_review','applied','oa',"
            "'interview','final_round','rejected','withdrawn','offer','closed')",
            name="status_values",
        ),
    )


class ApplicationEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "application_events"
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(40))
    new_status: Mapped[str | None] = mapped_column(String(40))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    application: Mapped[Application] = relationship(back_populates="events")


class ResearchSource(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "research_sources"
    company_id: Mapped[UUID | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    author: Mapped[str | None] = mapped_column(String(255))
    publisher: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_path: Mapped[str | None] = mapped_column(Text)
    normalized_path: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    language: Mapped[str | None] = mapped_column(String(20))
    source_quality: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unknown", server_default="unknown"
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    company: Mapped[Company | None] = relationship(back_populates="sources")
    documents: Mapped[list[ResearchDocument]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )
    claims: Mapped[list[ResearchClaim]] = relationship(back_populates="source")
    fetch_errors: Mapped[list[FetchError]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list[SourceArtifact]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )
    __table_args__ = (
        CheckConstraint(
            "source_quality IN ('official','high','medium','low','unknown')", name="quality_values"
        ),
    )


class FetchError(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "fetch_errors"
    source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_sources.id", ondelete="SET NULL")
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error_type: Mapped[str] = mapped_column(String(120), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    source: Mapped[ResearchSource | None] = relationship(back_populates="fetch_errors")


class SourceArtifact(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "source_artifacts"
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_sources.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    local_path: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    response_headers: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    source: Mapped[ResearchSource] = relationship(back_populates="artifacts")
    __table_args__ = (
        UniqueConstraint("source_id", "version", name="uq_source_artifacts_source_version"),
        UniqueConstraint("source_id", "content_hash", name="uq_source_artifacts_source_hash"),
    )


class ResearchFetchQueue(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "research_fetch_queue"
    company_id: Mapped[UUID | None] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    score_reasons: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="candidate", server_default="candidate"
    )
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        UniqueConstraint("company_id", "canonical_url"),
        CheckConstraint(
            "status IN ('candidate','queued','fetched','normalized','ignored','failed','blocked')",
            name="status_values",
        ),
        CheckConstraint("score >= 0 AND score <= 1", name="score_range"),
    )


class SearchUsage(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "search_usage"
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    company_id: Mapped[UUID | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    query_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    result_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )


class ResearchQuery(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "research_queries"
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    role_family_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("role_families.id", ondelete="SET NULL")
    )
    recruiting_cycle: Mapped[str | None] = mapped_column(String(40))
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    results: Mapped[list[ResearchSearchResult]] = relationship(
        back_populates="query", cascade="all, delete-orphan"
    )


class ResearchSearchResult(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "research_search_results"
    query_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_queries.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    result_rank: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String(500))
    snippet: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    role_family_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("role_families.id", ondelete="SET NULL")
    )
    recruiting_cycle: Mapped[str | None] = mapped_column(String(40))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    query: Mapped[ResearchQuery] = relationship(back_populates="results")
    __table_args__ = (UniqueConstraint("query_id", "canonical_url"),)


class InterviewStage(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "interview_stages"
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    reports: Mapped[list[InterviewReport]] = relationship(back_populates="stage_ref")
    resources: Mapped[list[ResourceInterviewStage]] = relationship(
        back_populates="stage", cascade="all, delete-orphan"
    )


class ResearchDocument(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "research_documents"
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_sources.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[UUID | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    document_type: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    markdown_path: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    source: Mapped[ResearchSource] = relationship(back_populates="documents")
    claims: Mapped[list[ResearchClaim]] = relationship(back_populates="document")
    extractions: Mapped[list[StructuredExtraction]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    __table_args__ = (UniqueConstraint("source_id", "version"),)


class ResearchClaim(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "research_claims"
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_sources.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_documents.id", ondelete="SET NULL")
    )
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    source: Mapped[ResearchSource] = relationship(back_populates="claims")
    document: Mapped[ResearchDocument | None] = relationship(back_populates="claims")
    __table_args__ = (
        CheckConstraint(
            "claim_type IN ('fact','inference','anecdote','opinion')", name="claim_type_values"
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )


class StructuredExtraction(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "structured_extractions"
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_documents.id", ondelete="CASCADE"), nullable=False
    )
    extraction_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    provenance_start: Mapped[int | None] = mapped_column(Integer)
    provenance_end: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    method: Mapped[str] = mapped_column(String(80), nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    document: Mapped[ResearchDocument] = relationship(back_populates="extractions")
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )


class FirmIntelligenceItem(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "firm_intelligence_items"
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5, server_default="0.5"
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    company: Mapped[Company] = relationship(back_populates="intelligence_items")
    sources: Mapped[list[FirmIntelligenceSource]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )
    matches: Mapped[list[CandidateFirmMatch]] = relationship(back_populates="item")
    __table_args__ = (
        CheckConstraint(
            "item_type IN ('theme','value','team','program','talking_point')",
            name="item_type_values",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )


class FirmIntelligenceSource(Base):
    __tablename__ = "firm_intelligence_sources"
    item_id: Mapped[UUID] = mapped_column(
        ForeignKey("firm_intelligence_items.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_sources.id", ondelete="CASCADE"), primary_key=True
    )
    claim_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_claims.id", ondelete="SET NULL")
    )
    item: Mapped[FirmIntelligenceItem] = relationship(back_populates="sources")
    source: Mapped[ResearchSource] = relationship()
    claim: Mapped[ResearchClaim | None] = relationship()


class CandidateFirmMatch(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "candidate_firm_matches"
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_evidence.id", ondelete="CASCADE"), nullable=False
    )
    intelligence_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("firm_intelligence_items.id", ondelete="CASCADE"), nullable=False
    )
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str] = mapped_column(
        String(40), nullable=False, default="manual", server_default="manual"
    )
    approved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    company: Mapped[Company] = relationship()
    evidence: Mapped[CandidateEvidence] = relationship()
    item: Mapped[FirmIntelligenceItem] = relationship(back_populates="matches")
    __table_args__ = (
        UniqueConstraint("evidence_id", "intelligence_item_id"),
        CheckConstraint(
            "relevance_score >= 0 AND relevance_score <= 1", name="relevance_score_range"
        ),
    )


class RecruitingCycle(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "recruiting_cycles"
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    role_family: Mapped[str] = mapped_column(String(80), nullable=False)
    internship_cycle: Mapped[str] = mapped_column(String(40), nullable=False)
    region: Mapped[str | None] = mapped_column(String(120))
    applications_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applications_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_oa_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_interview_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_offer_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    events: Mapped[list[RecruitingEvent]] = relationship(
        back_populates="cycle", cascade="all, delete-orphan"
    )
    __table_args__ = (
        UniqueConstraint("company_id", "role_family", "internship_cycle", "region"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )


class RecruitingEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "recruiting_events"
    recruiting_cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("recruiting_cycles.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_sources.id", ondelete="RESTRICT"), nullable=False
    )
    role_family_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("role_families.id", ondelete="SET NULL")
    )
    stage_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("interview_stages.id", ondelete="SET NULL")
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extraction_method: Mapped[str | None] = mapped_column(String(80))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    cycle: Mapped[RecruitingCycle] = relationship(back_populates="events")
    source: Mapped[ResearchSource] = relationship()


class InterviewReport(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "interview_reports"
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    role_family: Mapped[str] = mapped_column(String(80), nullable=False)
    internship_cycle: Mapped[str | None] = mapped_column(String(40))
    location: Mapped[str | None] = mapped_column(String(255))
    stage: Mapped[str | None] = mapped_column(String(120))
    stage_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("interview_stages.id", ondelete="SET NULL")
    )
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_sources.id", ondelete="RESTRICT"), nullable=False
    )
    reliability: Mapped[float] = mapped_column(Float, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    questions: Mapped[list[InterviewReportQuestion]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
    stage_ref: Mapped[InterviewStage | None] = relationship(back_populates="reports")


class InterviewQuestion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "interview_questions"
    canonical_question: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_question: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    answer_or_solution: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[str | None] = mapped_column(String(40))
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_sources.id", ondelete="SET NULL")
    )
    company_id: Mapped[UUID | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    role_family_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("role_families.id", ondelete="SET NULL")
    )
    stage_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("interview_stages.id", ondelete="SET NULL")
    )
    recruiting_cycle: Mapped[str | None] = mapped_column(String(40))
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    original_text: Mapped[str | None] = mapped_column(Text)
    provenance_start: Mapped[int | None] = mapped_column(Integer)
    provenance_end: Mapped[int | None] = mapped_column(Integer)
    question_kind: Mapped[str] = mapped_column(
        String(30), nullable=False, default="observed", server_default="observed"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    reports: Mapped[list[InterviewReportQuestion]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )
    skills: Mapped[list[InterviewQuestionSkill]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )
    attempts: Mapped[list[QuestionAttempt]] = relationship(back_populates="question")


class InterviewReportQuestion(Base):
    __tablename__ = "interview_report_questions"
    report_id: Mapped[UUID] = mapped_column(
        ForeignKey("interview_reports.id", ondelete="CASCADE"), primary_key=True
    )
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("interview_questions.id", ondelete="CASCADE"), primary_key=True
    )
    context: Mapped[str | None] = mapped_column(Text)
    report: Mapped[InterviewReport] = relationship(back_populates="questions")
    question: Mapped[InterviewQuestion] = relationship(back_populates="reports")


class Skill(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "skills"
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("skills.id", ondelete="SET NULL"))
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    parent: Mapped[Skill | None] = relationship(remote_side="Skill.id", back_populates="children")
    children: Mapped[list[Skill]] = relationship(back_populates="parent")
    jobs: Mapped[list[JobSkill]] = relationship(
        back_populates="skill", cascade="all, delete-orphan"
    )
    questions: Mapped[list[InterviewQuestionSkill]] = relationship(
        back_populates="skill", cascade="all, delete-orphan"
    )


class JobSkill(Base):
    __tablename__ = "job_skills"
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True
    )
    importance: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, server_default="1"
    )
    job: Mapped[Job] = relationship(back_populates="skills")
    skill: Mapped[Skill] = relationship(back_populates="jobs")


class InterviewQuestionSkill(Base):
    __tablename__ = "interview_question_skills"
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("interview_questions.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True
    )
    strength: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1")
    question: Mapped[InterviewQuestion] = relationship(back_populates="skills")
    skill: Mapped[Skill] = relationship(back_populates="questions")


class Resource(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "resources"
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    author: Mapped[str | None] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[str | None] = mapped_column(String(40))
    free: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    skills: Mapped[list[ResourceSkill]] = relationship(
        back_populates="resource", cascade="all, delete-orphan"
    )
    role_families: Mapped[list[ResourceRoleFamily]] = relationship(
        back_populates="resource", cascade="all, delete-orphan"
    )
    companies: Mapped[list[ResourceCompany]] = relationship(
        back_populates="resource", cascade="all, delete-orphan"
    )
    interview_stages: Mapped[list[ResourceInterviewStage]] = relationship(
        back_populates="resource", cascade="all, delete-orphan"
    )
    sections: Mapped[list[ResourceSection]] = relationship(
        back_populates="resource", cascade="all, delete-orphan"
    )


class ResourceSkill(Base):
    __tablename__ = "resource_skills"
    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True
    )
    section_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    resource: Mapped[Resource] = relationship(back_populates="skills")
    skill: Mapped[Skill] = relationship()


class ResourceSection(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "resource_sections"
    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("resource_sections.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    section_type: Mapped[str] = mapped_column(String(80), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    url: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    resource: Mapped[Resource] = relationship(back_populates="sections")
    parent: Mapped[ResourceSection | None] = relationship(
        remote_side="ResourceSection.id", back_populates="children"
    )
    children: Mapped[list[ResourceSection]] = relationship(back_populates="parent")
    skills: Mapped[list[ResourceSectionSkill]] = relationship(
        back_populates="section", cascade="all, delete-orphan"
    )


class ResourceSectionSkill(Base):
    __tablename__ = "resource_section_skills"
    section_id: Mapped[UUID] = mapped_column(
        ForeignKey("resource_sections.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True
    )
    strength: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1")
    section: Mapped[ResourceSection] = relationship(back_populates="skills")
    skill: Mapped[Skill] = relationship()


class ResourceRoleFamily(Base):
    __tablename__ = "resource_role_families"
    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True
    )
    role_family_id: Mapped[UUID] = mapped_column(
        ForeignKey("role_families.id", ondelete="CASCADE"), primary_key=True
    )
    relevance: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1")
    resource: Mapped[Resource] = relationship(back_populates="role_families")
    role_family: Mapped[RoleFamily] = relationship()


class ResourceCompany(Base):
    __tablename__ = "resource_companies"
    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True
    )
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    relevance: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1")
    resource: Mapped[Resource] = relationship(back_populates="companies")
    company: Mapped[Company] = relationship(back_populates="resources")


class ResourceInterviewStage(Base):
    __tablename__ = "resource_interview_stages"
    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True
    )
    interview_stage_id: Mapped[UUID] = mapped_column(
        ForeignKey("interview_stages.id", ondelete="CASCADE"), primary_key=True
    )
    relevance: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1")
    resource: Mapped[Resource] = relationship(back_populates="interview_stages")
    stage: Mapped[InterviewStage] = relationship(back_populates="resources")


class CandidateExperience(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "candidate_experiences"
    experience_type: Mapped[str] = mapped_column(String(80), nullable=False)
    organization: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    evidence: Mapped[list[CandidateEvidence]] = relationship(
        back_populates="experience", cascade="all, delete-orphan"
    )


class CandidateEvidence(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "candidate_evidence"
    experience_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("candidate_experiences.id", ondelete="SET NULL")
    )
    evidence_type: Mapped[str] = mapped_column(String(80), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    metric_name: Mapped[str | None] = mapped_column(String(120))
    metric_value: Mapped[str | None] = mapped_column(String(120))
    metric_unit: Mapped[str | None] = mapped_column(String(80))
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_quality: Mapped[str] = mapped_column(
        String(40), nullable=False, default="self_reported", server_default="self_reported"
    )
    approved_for_application: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    source_reference: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    experience: Mapped[CandidateExperience | None] = relationship(back_populates="evidence")
    skills: Mapped[list[CandidateEvidenceSkill]] = relationship(
        back_populates="evidence", cascade="all, delete-orphan"
    )


class CandidateEvidenceSkill(Base):
    __tablename__ = "candidate_evidence_skills"
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_evidence.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True
    )
    strength: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1")
    evidence: Mapped[CandidateEvidence] = relationship(back_populates="skills")
    skill: Mapped[Skill] = relationship()


class CVVersion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "cv_versions"
    application_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    template_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_path: Mapped[str | None] = mapped_column(Text)
    output_path: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approval_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="draft", server_default="draft"
    )
    provenance_review_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    application: Mapped[Application | None] = relationship(back_populates="cv_versions")


class ApplicationQuestion(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "application_questions"
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_question: Mapped[str] = mapped_column(Text, nullable=False)
    max_words: Mapped[int | None] = mapped_column(Integer)
    max_characters: Mapped[int | None] = mapped_column(Integer)
    required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, default="other", server_default="other"
    )
    application: Mapped[Application] = relationship(back_populates="questions")
    answers: Mapped[list[ApplicationAnswer]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )


class ApplicationAnswer(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "application_answers"
    application_question_id: Mapped[UUID] = mapped_column(
        ForeignKey("application_questions.id", ondelete="CASCADE"), nullable=False
    )
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    approved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    specificity_score: Mapped[int | None] = mapped_column(Integer)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    question: Mapped[ApplicationQuestion] = relationship(back_populates="answers")
    __table_args__ = (UniqueConstraint("application_question_id", "version"),)


class QuestionAttempt(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "question_attempts"
    interview_question_id: Mapped[UUID] = mapped_column(
        ForeignKey("interview_questions.id", ondelete="CASCADE"), nullable=False
    )
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    correct: Mapped[bool | None] = mapped_column(Boolean)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    question: Mapped[InterviewQuestion] = relationship(back_populates="attempts")


class AITask(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "ai_tasks"
    task_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default="pending"
    )
    input_manifest_path: Mapped[str | None] = mapped_column(Text)
    output_manifest_path: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prompt_version: Mapped[str] = mapped_column(
        String(40), nullable=False, default="v1", server_default="v1"
    )
    expected_output_schema: Mapped[str | None] = mapped_column(String(120))
    validation_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default="pending"
    )
    approval_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="draft", server_default="draft"
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(255))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','ready','in_progress','completed','failed')", name="status_values"
        ),
    )


class RefreshTarget(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "refresh_targets"
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    cadence_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successful_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", server_default="active"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id"),
        CheckConstraint("cadence_seconds > 0", name="cadence_positive"),
        CheckConstraint("failure_count >= 0", name="failure_count_nonnegative"),
    )


class AIPromptVersion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "ai_prompt_versions"
    task_type: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    template_path: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    __table_args__ = (UniqueConstraint("task_type", "version"),)


class AITaskRun(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "ai_task_runs"
    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_tasks.id", ondelete="CASCADE"), nullable=False
    )
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    output_path: Mapped[str] = mapped_column(Text, nullable=False)
    validation_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="created")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    task: Mapped[AITask] = relationship()
    __table_args__ = (UniqueConstraint("task_id", "run_number"),)


class AITaskOutput(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "ai_task_outputs"
    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_tasks.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_task_runs.id", ondelete="CASCADE"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    raw_path: Mapped[str] = mapped_column(Text, nullable=False)
    validation_status: Mapped[str] = mapped_column(String(30), nullable=False)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )


class ApplicationArgument(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "application_arguments"
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    role_family_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("role_families.id", ondelete="SET NULL")
    )
    team_or_program: Mapped[str | None] = mapped_column(String(255))
    argument_type: Mapped[str] = mapped_column(String(50), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    specificity_score: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    strength_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5, server_default="0.5"
    )
    approved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="draft", server_default="draft"
    )
    ai_task_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_tasks.id", ondelete="SET NULL"))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        CheckConstraint(
            "specificity_score >= 0 AND specificity_score <= 5", name="specificity_range"
        ),
        CheckConstraint("strength_score >= 0 AND strength_score <= 1", name="strength_range"),
    )


class ApplicationArgumentEvidence(Base):
    __tablename__ = "application_argument_evidence"
    argument_id: Mapped[UUID] = mapped_column(
        ForeignKey("application_arguments.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_evidence.id", ondelete="CASCADE"), primary_key=True
    )


class ApplicationArgumentSource(Base):
    __tablename__ = "application_argument_sources"
    argument_id: Mapped[UUID] = mapped_column(
        ForeignKey("application_arguments.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_sources.id", ondelete="CASCADE"), primary_key=True
    )


class ApplicationGap(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "application_gaps"
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    requirement: Mapped[str] = mapped_column(Text, nullable=False)
    gap_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(
        String(30), nullable=False, default="unknown", server_default="unknown"
    )
    evidence: Mapped[str | None] = mapped_column(Text)
    resolvable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    suggested_preparation: Mapped[str | None] = mapped_column(Text)
    ai_task_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_tasks.id", ondelete="SET NULL"))
    approved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="draft", server_default="draft"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )


class ApplicationRequirement(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "application_requirements"
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    requirement: Mapped[str] = mapped_column(Text, nullable=False)
    classification: Mapped[str] = mapped_column(
        String(30), nullable=False, default="unknown", server_default="unknown"
    )
    match_strength: Mapped[float] = mapped_column(
        Float, nullable=False, default=0, server_default="0"
    )
    ai_task_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_tasks.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="draft", server_default="draft"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        CheckConstraint("match_strength >= 0 AND match_strength <= 1", name="match_strength_range"),
        UniqueConstraint("application_id", "requirement"),
    )


class ApplicationRequirementEvidence(Base):
    __tablename__ = "application_requirement_evidence"
    requirement_id: Mapped[UUID] = mapped_column(
        ForeignKey("application_requirements.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_evidence.id", ondelete="CASCADE"), primary_key=True
    )


class CVBullet(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "cv_bullets"
    cv_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("cv_versions.id", ondelete="CASCADE"), nullable=False
    )
    experience_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("candidate_experiences.id", ondelete="SET NULL")
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_by_task: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_tasks.id", ondelete="SET NULL")
    )
    approved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="draft", server_default="draft"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )


class CVBulletEvidence(Base):
    __tablename__ = "cv_bullet_evidence"
    bullet_id: Mapped[UUID] = mapped_column(
        ForeignKey("cv_bullets.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_evidence.id", ondelete="CASCADE"), primary_key=True
    )


class CandidateStory(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "candidate_stories"
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    situation: Mapped[str] = mapped_column(Text, nullable=False)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    approved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="draft", server_default="draft"
    )
    ai_task_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_tasks.id", ondelete="SET NULL"))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )


class CandidateStoryEvidence(Base):
    __tablename__ = "candidate_story_evidence"
    story_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_stories.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_evidence.id", ondelete="CASCADE"), primary_key=True
    )


class CandidateProfile(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "candidate_profiles"
    legal_name: Mapped[str | None] = mapped_column(String(255))
    preferred_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(80))
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    github_url: Mapped[str | None] = mapped_column(Text)
    website_url: Mapped[str | None] = mapped_column(Text)
    university: Mapped[str | None] = mapped_column(String(255))
    degree: Mapped[str | None] = mapped_column(String(255))
    degree_subject: Mapped[str | None] = mapped_column(String(255))
    graduation_date: Mapped[date | None] = mapped_column(Date)
    locations: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    address: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )


class SensitiveField(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "candidate_sensitive_fields"
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False
    )
    field_name: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="unresolved", server_default="unresolved"
    )
    explicitly_entered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    approved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (UniqueConstraint("profile_id", "field_name"),)


class CandidateCVSection(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "candidate_cv_sections"
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False
    )
    section_key: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (UniqueConstraint("profile_id", "section_key"),)


class CandidateCVEntry(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "candidate_cv_entries"
    section_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_cv_sections.id", ondelete="CASCADE"), nullable=False
    )
    experience_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("candidate_experiences.id", ondelete="SET NULL")
    )
    evidence_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("candidate_evidence.id", ondelete="SET NULL")
    )
    label_override: Mapped[str | None] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    default_inclusion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )


class ApplicationArtifact(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "application_artifacts"
    application_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE")
    )
    artifact_type: Mapped[str] = mapped_column(String(60), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="draft", server_default="draft"
    )
    source_task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_tasks.id", ondelete="SET NULL")
    )
    source_task_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_task_runs.id", ondelete="SET NULL")
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_path: Mapped[str | None] = mapped_column(Text)
    rendered_path: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(120))
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (UniqueConstraint("application_id", "artifact_type", "version"),)


class ArtifactProvenance(Base):
    __tablename__ = "artifact_provenance"
    artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("application_artifacts.id", ondelete="CASCADE"), primary_key=True
    )
    entity_type: Mapped[str] = mapped_column(String(60), primary_key=True)
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    relation: Mapped[str] = mapped_column(
        String(60), nullable=False, default="supports", server_default="supports"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )


class ApplicationAnswerEvidence(Base):
    __tablename__ = "application_answer_evidence"
    answer_id: Mapped[UUID] = mapped_column(
        ForeignKey("application_answers.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_evidence.id", ondelete="CASCADE"), primary_key=True
    )


class ApplicationAnswerSource(Base):
    __tablename__ = "application_answer_sources"
    answer_id: Mapped[UUID] = mapped_column(
        ForeignKey("application_answers.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_sources.id", ondelete="CASCADE"), primary_key=True
    )


class CoverLetterBlock(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "cover_letter_blocks"
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    block_type: Mapped[str] = mapped_column(String(40), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    approved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    provenance_review_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    source_task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_tasks.id", ondelete="SET NULL")
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )


class CoverLetterBlockEvidence(Base):
    __tablename__ = "cover_letter_block_evidence"
    block_id: Mapped[UUID] = mapped_column(
        ForeignKey("cover_letter_blocks.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_evidence.id", ondelete="CASCADE"), primary_key=True
    )


class CoverLetterBlockSource(Base):
    __tablename__ = "cover_letter_block_sources"
    block_id: Mapped[UUID] = mapped_column(
        ForeignKey("cover_letter_blocks.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_sources.id", ondelete="CASCADE"), primary_key=True
    )


class ReviewEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "review_events"
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    application_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE")
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(30))
    new_status: Mapped[str | None] = mapped_column(String(30))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )


class BrowserFillRun(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "browser_fill_runs"
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="reserved", server_default="reserved"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )


class BrowserFieldMapping(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "browser_field_mappings"
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("browser_fill_runs.id", ondelete="CASCADE"), nullable=False
    )
    field_label: Mapped[str] = mapped_column(String(255), nullable=False)
    field_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_entity_type: Mapped[str | None] = mapped_column(String(60))
    source_entity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    expected_value_hash: Mapped[str | None] = mapped_column(String(64))
    actual_value_hash: Mapped[str | None] = mapped_column(String(64))
    fill_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="not_run", server_default="not_run"
    )
    validation_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="not_run", server_default="not_run"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )


class SharedTombstone(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A public shared object removed from the dataset and reported to clients."""

    __tablename__ = "shared_tombstones"
    collection: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (UniqueConstraint("collection", "entity_id"),)
