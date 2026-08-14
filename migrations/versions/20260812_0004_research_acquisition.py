"""Add V4 acquisition artifacts, queues, extraction, and resource sections."""

import sqlalchemy as sa
from alembic import context, op

from quant_recruiting.db.models import (
    ResearchFetchQueue,
    ResourceSection,
    ResourceSectionSkill,
    SearchUsage,
    SourceArtifact,
    StructuredExtraction,
)

revision = "20260812_0004"
down_revision = "20260812_0003"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    from sqlalchemy import inspect

    return column in {item["name"] for item in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    for table in (
        SourceArtifact.__table__,
        ResearchFetchQueue.__table__,
        SearchUsage.__table__,
        StructuredExtraction.__table__,
        ResourceSection.__table__,
        ResourceSectionSkill.__table__,
    ):
        table.create(bind=bind, checkfirst=True)
    if context.is_offline_mode() or not _column_exists("research_search_results", "published_at"):
        op.add_column(
            "research_search_results",
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        )

    if context.is_offline_mode() or not _column_exists("recruiting_events", "role_family_id"):
        op.add_column("recruiting_events", sa.Column("role_family_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            "fk_recruiting_events_role_family_id_role_families",
            "recruiting_events",
            "role_families",
            ["role_family_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if context.is_offline_mode() or not _column_exists("recruiting_events", "stage_id"):
        op.add_column("recruiting_events", sa.Column("stage_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            "fk_recruiting_events_stage_id_interview_stages",
            "recruiting_events",
            "interview_stages",
            ["stage_id"],
            ["id"],
            ondelete="SET NULL",
        )
    for name, column in (
        ("extracted_text", sa.Text()),
        ("extraction_method", sa.String(length=80)),
    ):
        if context.is_offline_mode() or not _column_exists("recruiting_events", name):
            op.add_column("recruiting_events", sa.Column(name, column, nullable=True))
    question_columns = {
        "company_id": sa.Uuid(),
        "role_family_id": sa.Uuid(),
        "stage_id": sa.Uuid(),
        "recruiting_cycle": sa.String(length=40),
        "extraction_confidence": sa.Float(),
        "original_text": sa.Text(),
        "provenance_start": sa.Integer(),
        "provenance_end": sa.Integer(),
    }
    question_foreign_keys = {
        "company_id": ("companies", "fk_interview_questions_company_id_companies"),
        "role_family_id": ("role_families", "fk_interview_questions_role_family_id_role_families"),
        "stage_id": ("interview_stages", "fk_interview_questions_stage_id_interview_stages"),
    }
    for name, column in question_columns.items():
        if context.is_offline_mode() or not _column_exists("interview_questions", name):
            op.add_column("interview_questions", sa.Column(name, column, nullable=True))
            if name in question_foreign_keys:
                referred, constraint = question_foreign_keys[name]
                op.create_foreign_key(
                    constraint, "interview_questions", referred, [name], ["id"], ondelete="SET NULL"
                )


def downgrade() -> None:
    for table in (
        ResourceSectionSkill.__table__,
        ResourceSection.__table__,
        StructuredExtraction.__table__,
        SearchUsage.__table__,
        ResearchFetchQueue.__table__,
        SourceArtifact.__table__,
    ):
        table.drop(bind=op.get_bind(), checkfirst=True)
    op.drop_column("research_search_results", "published_at")
    for name in (
        "provenance_end",
        "provenance_start",
        "original_text",
        "extraction_confidence",
        "recruiting_cycle",
        "stage_id",
        "role_family_id",
        "company_id",
    ):
        op.drop_column("interview_questions", name)
    for name in ("extraction_method", "extracted_text", "stage_id", "role_family_id"):
        op.drop_column("recruiting_events", name)
