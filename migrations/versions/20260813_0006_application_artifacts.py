"""Add V6 application artifacts, profiles, review, and browser contracts."""

import sqlalchemy as sa
from alembic import context, op

from quant_recruiting.db.models import (
    ApplicationAnswerEvidence,
    ApplicationAnswerSource,
    ApplicationArtifact,
    ArtifactProvenance,
    BrowserFieldMapping,
    BrowserFillRun,
    CandidateCVEntry,
    CandidateCVSection,
    CandidateProfile,
    CoverLetterBlock,
    CoverLetterBlockEvidence,
    CoverLetterBlockSource,
    ReviewEvent,
    SensitiveField,
)

revision = "20260813_0006"
down_revision = "20260812_0005"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    from sqlalchemy import inspect

    return {column["name"] for column in inspect(op.get_bind()).get_columns(table)}


def _add_column(table: str, column: sa.Column) -> None:
    if context.is_offline_mode() or column.name not in _columns(table):
        op.add_column(table, column)


def upgrade() -> None:
    for table in (
        CandidateProfile.__table__,
        SensitiveField.__table__,
        CandidateCVSection.__table__,
        CandidateCVEntry.__table__,
        ApplicationArtifact.__table__,
        ArtifactProvenance.__table__,
        ApplicationAnswerEvidence.__table__,
        ApplicationAnswerSource.__table__,
        CoverLetterBlock.__table__,
        CoverLetterBlockEvidence.__table__,
        CoverLetterBlockSource.__table__,
        ReviewEvent.__table__,
        BrowserFillRun.__table__,
        BrowserFieldMapping.__table__,
    ):
        table.create(bind=op.get_bind(), checkfirst=True)

    _add_column("applications", sa.Column("application_url", sa.Text(), nullable=True))
    _add_column(
        "applications",
        sa.Column(
            "cover_letter_requirement",
            sa.String(length=20),
            nullable=False,
            server_default="unknown",
        ),
    )
    _add_column(
        "cv_versions",
        sa.Column("approval_status", sa.String(length=30), nullable=False, server_default="draft"),
    )
    _add_column(
        "cv_versions",
        sa.Column(
            "provenance_review_required", sa.Boolean(), nullable=False, server_default="false"
        ),
    )


def downgrade() -> None:
    for table in (
        BrowserFieldMapping.__table__,
        BrowserFillRun.__table__,
        ReviewEvent.__table__,
        CoverLetterBlockSource.__table__,
        CoverLetterBlockEvidence.__table__,
        CoverLetterBlock.__table__,
        ApplicationAnswerSource.__table__,
        ApplicationAnswerEvidence.__table__,
        ArtifactProvenance.__table__,
        ApplicationArtifact.__table__,
        CandidateCVEntry.__table__,
        CandidateCVSection.__table__,
        SensitiveField.__table__,
        CandidateProfile.__table__,
    ):
        table.drop(bind=op.get_bind(), checkfirst=True)
    op.drop_column("cv_versions", "provenance_review_required")
    op.drop_column("cv_versions", "approval_status")
    op.drop_column("applications", "cover_letter_requirement")
    op.drop_column("applications", "application_url")
