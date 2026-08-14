"""SQLite-only tables for cache state, conversations, and local audit metadata."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from quant_recruiting.db.base import Base, CreatedAtMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin


class LocalSyncState(Base):
    __tablename__ = "local_sync_state"
    category: Mapped[str] = mapped_column(String(60), primary_key=True)
    shared_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    shared_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stale_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_server: Mapped[str | None] = mapped_column(String(255))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="current")
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalSyncCursor(Base):
    __tablename__ = "local_sync_cursors"
    transport: Mapped[str] = mapped_column(String(40), primary_key=True)
    cursor: Mapped[str | None] = mapped_column(String(255))
    dataset_version: Mapped[str | None] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalSharedCache(Base):
    __tablename__ = "local_shared_cache"
    category: Mapped[str] = mapped_column(String(60), primary_key=True)
    shared_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    shared_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stale_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_server: Mapped[str | None] = mapped_column(String(255))
    content_hash: Mapped[str | None] = mapped_column(String(64))


class LocalApplicationReference(Base):
    __tablename__ = "local_application_references"
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True
    )
    shared_company_id: Mapped[str | None] = mapped_column(String(80))
    shared_job_id: Mapped[str | None] = mapped_column(String(80))
    shared_source_server: Mapped[str | None] = mapped_column(String(255))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class AIConversation(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "ai_conversations"
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    external_conversation_id: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(500))
    application_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL")
    )
    company_id: Mapped[UUID | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_tasks.id", ondelete="SET NULL"))
    source_method: Mapped[str] = mapped_column(String(80), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_path: Mapped[str | None] = mapped_column(Text)
    markdown_path: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (UniqueConstraint("provider", "external_conversation_id"),)


class AIConversationMessage(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "ai_conversation_messages"
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (UniqueConstraint("conversation_id", "sequence"),)


class AIConversationAttachment(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "ai_conversation_attachments"
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_conversation_messages.id", ondelete="CASCADE")
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    media_type: Mapped[str | None] = mapped_column(String(120))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class AIConversationLink(Base):
    __tablename__ = "ai_conversation_links"
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"), primary_key=True
    )
    entity_type: Mapped[str] = mapped_column(String(60), primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    relation: Mapped[str] = mapped_column(String(60), nullable=False, default="context")


class AIConversationAnnotation(Base):
    __tablename__ = "ai_conversation_annotations"
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_conversation_messages.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LocalPublishIntent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "local_publish_intents"
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    destination: Mapped[str] = mapped_column(String(255), nullable=False)
    preview_path: Mapped[str | None] = mapped_column(Text)
    sanitized_payload_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalBrowserRun(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """Local-only lifecycle state for one Playwright application run."""

    __tablename__ = "browser_runs"
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    payload_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("application_artifacts.id", ondelete="SET NULL")
    )
    packet_version: Mapped[int | None] = mapped_column(Integer)
    application_url: Mapped[str] = mapped_column(Text, nullable=False)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text)
    detected_ats: Mapped[str | None] = mapped_column(String(40))
    ats_confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="created")
    browser_type: Mapped[str] = mapped_column(String(30), nullable=False, default="chromium")
    headless: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    current_step: Mapped[str | None] = mapped_column(String(120))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    screenshot_dir: Mapped[str] = mapped_column(Text, nullable=False)
    form_snapshot_path: Mapped[str | None] = mapped_column(Text)
    fill_log_path: Mapped[str | None] = mapped_column(Text)
    review_html_path: Mapped[str | None] = mapped_column(Text)
    dogfood: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    feedback_status: Mapped[str | None] = mapped_column(String(30))
    feedback_note: Mapped[str | None] = mapped_column(Text)
    manual_intervention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalBrowserPage(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "browser_pages"
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("browser_runs.id", ondelete="CASCADE"), nullable=False
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    snapshot_path: Mapped[str | None] = mapped_column(Text)
    inspected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (UniqueConstraint("run_id", "step_index"),)


class LocalBrowserField(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "browser_fields"
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("browser_runs.id", ondelete="CASCADE"), nullable=False
    )
    page_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("browser_pages.id", ondelete="SET NULL")
    )
    field_key: Mapped[str] = mapped_column(String(255), nullable=False)
    original_label: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_key: Mapped[str | None] = mapped_column(String(120))
    field_type: Mapped[str] = mapped_column(String(40), nullable=False)
    input_type: Mapped[str | None] = mapped_column(String(40))
    html_name: Mapped[str | None] = mapped_column(String(255))
    html_id: Mapped[str | None] = mapped_column(String(255))
    aria_label: Mapped[str | None] = mapped_column(Text)
    placeholder: Mapped[str | None] = mapped_column(Text)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    options: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    current_value_hash: Mapped[str | None] = mapped_column(String(64))
    mapping_confidence: Mapped[str] = mapped_column(String(20), nullable=False, default="unmapped")
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="unresolved")
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalBrowserFieldMapping(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "local_browser_field_mappings"
    field_id: Mapped[UUID] = mapped_column(
        ForeignKey("browser_fields.id", ondelete="CASCADE"), nullable=False
    )
    source_entity_type: Mapped[str | None] = mapped_column(String(60))
    source_entity_id: Mapped[str | None] = mapped_column(String(80))
    source_key: Mapped[str | None] = mapped_column(String(120))
    method: Mapped[str] = mapped_column(String(60), nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    expected_value_hash: Mapped[str | None] = mapped_column(String(64))
    actual_value_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="mapped")
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalBrowserFillAttempt(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "browser_fill_attempts"
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("browser_runs.id", ondelete="CASCADE"), nullable=False
    )
    field_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("browser_fields.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    expected_value_hash: Mapped[str | None] = mapped_column(String(64))
    actual_value_hash: Mapped[str | None] = mapped_column(String(64))
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalBrowserUpload(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "browser_uploads"
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("browser_runs.id", ondelete="CASCADE"), nullable=False
    )
    field_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("browser_fields.id", ondelete="SET NULL")
    )
    artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("application_artifacts.id", ondelete="RESTRICT"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(60), nullable=False)
    expected_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_filename: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalBrowserValidationError(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "browser_validation_errors"
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("browser_runs.id", ondelete="CASCADE"), nullable=False
    )
    field_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("browser_fields.id", ondelete="SET NULL")
    )
    page_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("browser_pages.id", ondelete="SET NULL")
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    error_type: Mapped[str] = mapped_column(String(50), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalBrowserFieldAlias(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "browser_field_aliases"
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_label: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_key: Mapped[str] = mapped_column(String(120), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="user")
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (UniqueConstraint("normalized_label", "normalized_key"),)


class LocalCandidateFormValue(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "candidate_form_values"
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False
    )
    normalized_key: Mapped[str] = mapped_column(String(120), nullable=False)
    original_question: Mapped[str | None] = mapped_column(Text)
    value: Mapped[str | None] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(String(30), nullable=False, default="text")
    sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reusable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (UniqueConstraint("profile_id", "normalized_key"),)


class LocalApplicationFormValue(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "application_form_values"
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    normalized_key: Mapped[str] = mapped_column(String(120), nullable=False)
    original_question: Mapped[str | None] = mapped_column(Text)
    value: Mapped[str | None] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(String(30), nullable=False, default="text")
    sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (UniqueConstraint("application_id", "normalized_key"),)


class LocalBrowserRunAttempt(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One execution attempt within a logical local browser run."""

    __tablename__ = "browser_run_attempts"
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("browser_runs.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="created")
    checkpoint: Mapped[str | None] = mapped_column(String(80))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(60))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (UniqueConstraint("run_id", "attempt_number"),)


class LocalBrowserParsedValue(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A value produced by an ATS parser, never canonical candidate data."""

    __tablename__ = "browser_parsed_values"
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("browser_runs.id", ondelete="CASCADE"), nullable=False
    )
    field_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("browser_fields.id", ondelete="SET NULL")
    )
    field: Mapped[str] = mapped_column(String(160), nullable=False)
    parsed_value: Mapped[str | None] = mapped_column(Text)
    expected_profile_value: Mapped[str | None] = mapped_column(Text)
    comparison_status: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="ats_parser")
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalBackgroundRun(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "background_runs"
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trigger: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    error_summary: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalBackgroundTaskResult(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "background_task_results"
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("background_runs.id", ondelete="CASCADE"), nullable=False
    )
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalJobAlertRule(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "job_alert_rules"
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    filters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalJobAlertMatch(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "job_alert_matches"
    rule_id: Mapped[UUID] = mapped_column(
        ForeignKey("job_alert_rules.id", ondelete="CASCADE"), nullable=False
    )
    shared_job_id: Mapped[str] = mapped_column(String(80), nullable=False)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notification_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("notifications.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="new")
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (UniqueConstraint("rule_id", "shared_job_id"),)


class LocalEmailAccount(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "email_accounts"
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    address: Mapped[str | None] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="disconnected")
    cursor: Mapped[str | None] = mapped_column(String(255))
    history_id: Mapped[str | None] = mapped_column(String(255))
    last_full_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (UniqueConstraint("provider", "address"),)


class LocalEmailThread(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "email_threads"
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("email_accounts.id", ondelete="CASCADE"), nullable=False
    )
    provider_thread_id: Mapped[str | None] = mapped_column(String(255))
    subject: Mapped[str | None] = mapped_column(Text)
    first_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (UniqueConstraint("account_id", "provider_thread_id"),)


class LocalEmailMessage(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "email_messages"
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("email_accounts.id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("email_threads.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    provider_thread_id: Mapped[str | None] = mapped_column(String(255))
    message_id_header: Mapped[str | None] = mapped_column(String(500))
    subject: Mapped[str | None] = mapped_column(Text)
    sender_name: Mapped[str | None] = mapped_column(String(255))
    sender_email: Mapped[str | None] = mapped_column(String(320))
    recipients: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    text_body: Mapped[str | None] = mapped_column(Text)
    html_body_path: Mapped[str | None] = mapped_column(Text)
    raw_path: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        UniqueConstraint("provider", "provider_message_id"),
        UniqueConstraint("provider", "message_id_header"),
        UniqueConstraint("provider", "content_hash"),
    )


class LocalEmailAttachment(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "email_attachments"
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("email_messages.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(160))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    local_path: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    downloaded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalEmailLink(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "email_links"
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("email_messages.id", ondelete="CASCADE"), nullable=False
    )
    application_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE")
    )
    company_id: Mapped[UUID | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    link_type: Mapped[str] = mapped_column(String(40), nullable=False, default="suggested")
    confidence: Mapped[float | None] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(60), nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalEmailExtraction(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "email_extractions"
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("email_messages.id", ondelete="CASCADE"), nullable=False
    )
    extraction_type: Mapped[str] = mapped_column(String(60), nullable=False)
    value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    text_span: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    method: Mapped[str] = mapped_column(String(60), nullable=False, default="rules")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="extracted")
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalAssessmentProvider(Base):
    __tablename__ = "assessment_providers"
    slug: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalTimelineEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "timeline_events"
    application_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone_name: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="observed")
    source_type: Mapped[str] = mapped_column(String(60), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalRecruitingAction(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "recruiting_actions"
    application_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    action_type: Mapped[str] = mapped_column(String(60), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_type: Mapped[str] = mapped_column(String(60), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(80))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalReminder(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "reminders"
    action_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("recruiting_actions.id", ondelete="CASCADE")
    )
    timeline_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("timeline_events.id", ondelete="CASCADE")
    )
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    delivery_method: Mapped[str] = mapped_column(String(40), nullable=False, default="dashboard")
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalInterviewAppointment(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "interview_appointments"
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    interview_stage: Mapped[str] = mapped_column(String(80), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone_name: Mapped[str] = mapped_column(String(80), nullable=False)
    format: Mapped[str | None] = mapped_column(String(60))
    location: Mapped[str | None] = mapped_column(Text)
    meeting_url: Mapped[str | None] = mapped_column(Text)
    interviewer_names: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    recruiter: Mapped[str | None] = mapped_column(String(255))
    source_email_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("email_messages.id", ondelete="SET NULL")
    )
    confirmation_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="needs_review"
    )
    notes: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalAssessment(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "assessments"
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    assessment_type: Mapped[str] = mapped_column(String(80), nullable=False)
    provider: Mapped[str] = mapped_column(String(60), nullable=False, default="other")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="received")
    source_email_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("email_messages.id", ondelete="SET NULL")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score_result: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalPrepPlan(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "prep_plans"
    application_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE")
    )
    assessment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE")
    )
    interview_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("interview_appointments.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    daily_minutes: Mapped[int | None] = mapped_column(Integer)
    rationale: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalPrepPlanItem(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "prep_plan_items"
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("prep_plans.id", ondelete="CASCADE"), nullable=False
    )
    skill_id: Mapped[UUID | None] = mapped_column(ForeignKey("skills.id", ondelete="SET NULL"))
    resource_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("resources.id", ondelete="SET NULL")
    )
    resource_section_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("resource_sections.id", ondelete="SET NULL")
    )
    question_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("interview_questions.id", ondelete="SET NULL")
    )
    priority: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completion_state: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    rationale: Mapped[str | None] = mapped_column(Text)
    source_intelligence: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalRecruitingContact(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "recruiting_contacts"
    company_id: Mapped[UUID | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    role_title: Mapped[str | None] = mapped_column(String(255))
    relationship_type: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    source_email_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("email_messages.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalInterviewNote(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "interview_notes"
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    interview_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("interview_appointments.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    questions_encountered: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    topics: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    reflections: Mapped[str | None] = mapped_column(Text)
    result_known: Mapped[str | None] = mapped_column(String(40))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalNotification(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "notifications"
    notification_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(80))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class LocalBrowserIssue(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """Private dogfooding issue record; never published automatically."""

    __tablename__ = "browser_issues"
    provider: Mapped[str | None] = mapped_column(String(40))
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("browser_runs.id", ondelete="SET NULL"))
    failure_category: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    fixture_captured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="P1")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )
