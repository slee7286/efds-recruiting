"""Add general recruiting taxonomy, ATS, research and refresh structures."""

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy import inspect

from quant_recruiting.db.models import (
    CandidateFirmMatch,
    CompanyATS,
    FirmIntelligenceItem,
    FirmIntelligenceSource,
    InterviewStage,
    RefreshTarget,
    ResearchQuery,
    ResearchSearchResult,
    ResourceCompany,
    ResourceInterviewStage,
    ResourceRoleFamily,
    RoleFamily,
)

revision = "20260812_0003"
down_revision = "20260812_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not context.is_offline_mode():
        inspector = inspect(op.get_bind())
        v3_tables = {
            "role_families",
            "company_ats",
            "research_queries",
            "research_search_results",
            "interview_stages",
            "firm_intelligence_items",
            "firm_intelligence_sources",
            "candidate_firm_matches",
            "resource_role_families",
            "resource_companies",
            "resource_interview_stages",
            "refresh_targets",
        }
        existing_tables = set(inspector.get_table_names())
        existing_columns = {
            table: {column["name"] for column in inspector.get_columns(table)}
            for table in ("jobs", "interview_reports", "application_answers")
        }
        if (
            v3_tables <= existing_tables
            and {
                "role_family_id",
                "company_ats_id",
                "classification_method",
                "classification_locked",
            }
            <= existing_columns["jobs"]
            and "stage_id" in existing_columns["interview_reports"]
            and "specificity_score" in existing_columns["application_answers"]
        ):
            return
    op.add_column("jobs", sa.Column("role_family_id", sa.Uuid(), nullable=True))
    op.add_column("jobs", sa.Column("company_ats_id", sa.Uuid(), nullable=True))
    op.add_column("jobs", sa.Column("classification_method", sa.String(length=40), nullable=True))
    op.add_column(
        "jobs",
        sa.Column("classification_locked", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("interview_reports", sa.Column("stage_id", sa.Uuid(), nullable=True))
    op.add_column(
        "application_answers", sa.Column("specificity_score", sa.Integer(), nullable=True)
    )

    bind = op.get_bind()
    for table in (
        RoleFamily.__table__,
        CompanyATS.__table__,
        ResearchQuery.__table__,
        ResearchSearchResult.__table__,
        InterviewStage.__table__,
        FirmIntelligenceItem.__table__,
        FirmIntelligenceSource.__table__,
        CandidateFirmMatch.__table__,
        ResourceRoleFamily.__table__,
        ResourceCompany.__table__,
        ResourceInterviewStage.__table__,
        RefreshTarget.__table__,
    ):
        table.create(bind=bind, checkfirst=True)

    op.create_foreign_key(
        "fk_jobs_role_family_id_role_families",
        "jobs",
        "role_families",
        ["role_family_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_jobs_company_ats_id_company_ats",
        "jobs",
        "company_ats",
        ["company_ats_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_interview_reports_stage_id_interview_stages",
        "interview_reports",
        "interview_stages",
        ["stage_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Older V1 databases may have constrained role_family to the original
    # quant-oriented values. Keep the historical column, but let the new
    # relational taxonomy carry the extensible classification.
    if not context.is_offline_mode():
        for constraint in inspect(bind).get_check_constraints("jobs"):
            name = constraint.get("name") or ""
            sqltext = constraint.get("sqltext") or ""
            if "role_family" in name or "role_family" in sqltext:
                op.drop_constraint(name, "jobs", type_="check")


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_constraint(
        "fk_interview_reports_stage_id_interview_stages", "interview_reports", type_="foreignkey"
    )
    op.drop_constraint("fk_jobs_company_ats_id_company_ats", "jobs", type_="foreignkey")
    op.drop_constraint("fk_jobs_role_family_id_role_families", "jobs", type_="foreignkey")
    for table in (
        RefreshTarget.__table__,
        ResourceInterviewStage.__table__,
        ResourceCompany.__table__,
        ResourceRoleFamily.__table__,
        CandidateFirmMatch.__table__,
        FirmIntelligenceSource.__table__,
        FirmIntelligenceItem.__table__,
        InterviewStage.__table__,
        ResearchSearchResult.__table__,
        ResearchQuery.__table__,
        CompanyATS.__table__,
        RoleFamily.__table__,
    ):
        table.drop(bind=bind, checkfirst=True)
    op.drop_column("application_answers", "specificity_score")
    op.drop_column("interview_reports", "stage_id")
    op.drop_column("jobs", "classification_locked")
    op.drop_column("jobs", "classification_method")
    op.drop_column("jobs", "company_ats_id")
    op.drop_column("jobs", "role_family_id")
