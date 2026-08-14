"""Add V5 interactive-AI contracts and application intelligence structures."""

import sqlalchemy as sa
from alembic import context, op

from quant_recruiting.db.models import (
    AIPromptVersion,
    AITaskOutput,
    AITaskRun,
    ApplicationArgument,
    ApplicationArgumentEvidence,
    ApplicationArgumentSource,
    ApplicationGap,
    ApplicationRequirement,
    ApplicationRequirementEvidence,
    CandidateStory,
    CandidateStoryEvidence,
    CVBullet,
    CVBulletEvidence,
)

revision = "20260812_0005"
down_revision = "20260812_0004"
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
        AIPromptVersion.__table__,
        AITaskRun.__table__,
        AITaskOutput.__table__,
        ApplicationArgument.__table__,
        ApplicationArgumentEvidence.__table__,
        ApplicationArgumentSource.__table__,
        ApplicationGap.__table__,
        ApplicationRequirement.__table__,
        ApplicationRequirementEvidence.__table__,
        CVBullet.__table__,
        CVBulletEvidence.__table__,
        CandidateStory.__table__,
        CandidateStoryEvidence.__table__,
    ):
        table.create(bind=op.get_bind(), checkfirst=True)

    _add_column(
        "ai_tasks",
        sa.Column("prompt_version", sa.String(length=40), nullable=False, server_default="v1"),
    )
    _add_column(
        "ai_tasks", sa.Column("expected_output_schema", sa.String(length=120), nullable=True)
    )
    _add_column(
        "ai_tasks",
        sa.Column(
            "validation_status", sa.String(length=30), nullable=False, server_default="pending"
        ),
    )
    _add_column(
        "ai_tasks",
        sa.Column("approval_status", sa.String(length=30), nullable=False, server_default="draft"),
    )
    _add_column("ai_tasks", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    _add_column("ai_tasks", sa.Column("approved_by", sa.String(length=255), nullable=True))
    _add_column(
        "candidate_evidence",
        sa.Column(
            "evidence_quality", sa.String(length=40), nullable=False, server_default="self_reported"
        ),
    )
    _add_column(
        "candidate_evidence",
        sa.Column("approved_for_application", sa.Boolean(), nullable=False, server_default="false"),
    )
    _add_column(
        "application_questions",
        sa.Column("category", sa.String(length=50), nullable=False, server_default="other"),
    )
    _add_column(
        "interview_questions",
        sa.Column("question_kind", sa.String(length=30), nullable=False, server_default="observed"),
    )


def downgrade() -> None:
    for table in (
        CandidateStoryEvidence.__table__,
        CandidateStory.__table__,
        CVBulletEvidence.__table__,
        CVBullet.__table__,
        ApplicationGap.__table__,
        ApplicationRequirementEvidence.__table__,
        ApplicationRequirement.__table__,
        ApplicationArgumentSource.__table__,
        ApplicationArgumentEvidence.__table__,
        ApplicationArgument.__table__,
        AITaskOutput.__table__,
        AITaskRun.__table__,
        AIPromptVersion.__table__,
    ):
        table.drop(bind=op.get_bind(), checkfirst=True)
    for table, column in (
        ("interview_questions", "question_kind"),
        ("application_questions", "category"),
        ("candidate_evidence", "approved_for_application"),
        ("candidate_evidence", "evidence_quality"),
        ("ai_tasks", "approved_by"),
        ("ai_tasks", "approved_at"),
        ("ai_tasks", "approval_status"),
        ("ai_tasks", "validation_status"),
        ("ai_tasks", "expected_output_schema"),
        ("ai_tasks", "prompt_version"),
    ):
        op.drop_column(table, column)
