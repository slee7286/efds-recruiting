"""Add V2 discovery, domain, fetch, and job history tables.

Revision ID: 20260812_0002
Revises: 20260812_0001
"""

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy import inspect

from quant_recruiting.db.models import (
    CompanyDomain,
    DiscoveredURL,
    FetchError,
    JobObservation,
)

revision = "20260812_0002"
down_revision = "20260812_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if context.is_offline_mode():
        op.drop_constraint("uq_research_documents_source_id", "research_documents", type_="unique")
        op.add_column(
            "companies", sa.Column("normalized_name", sa.String(length=255), nullable=True)
        )
        op.create_index("ix_companies_normalized_name", "companies", ["normalized_name"])
        op.add_column("jobs", sa.Column("classification_confidence", sa.Float(), nullable=True))
        op.create_check_constraint(
            "classification_confidence_range",
            "jobs",
            "classification_confidence IS NULL OR (classification_confidence >= 0 "
            "AND classification_confidence <= 1)",
        )
        op.add_column(
            "research_sources",
            sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.add_column(
            "research_sources",
            sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=True),
        )
    else:
        inspector = inspect(op.get_bind())
        if "content_hash" in [
            c["name"] for c in inspector.get_unique_constraints("research_documents")
        ]:
            op.drop_constraint(
                "uq_research_documents_source_id", "research_documents", type_="unique"
            )
        company_columns = {c["name"] for c in inspector.get_columns("companies")}
        if "normalized_name" not in company_columns:
            op.add_column(
                "companies", sa.Column("normalized_name", sa.String(length=255), nullable=True)
            )
            op.create_index("ix_companies_normalized_name", "companies", ["normalized_name"])
        job_columns = {c["name"] for c in inspector.get_columns("jobs")}
        if "classification_confidence" not in job_columns:
            op.add_column("jobs", sa.Column("classification_confidence", sa.Float(), nullable=True))
            op.create_check_constraint(
                "classification_confidence_range",
                "jobs",
                "classification_confidence IS NULL OR (classification_confidence >= 0 "
                "AND classification_confidence <= 1)",
            )
        source_columns = {c["name"] for c in inspector.get_columns("research_sources")}
        for name in ("last_fetched_at", "last_changed_at"):
            if name not in source_columns:
                op.add_column(
                    "research_sources", sa.Column(name, sa.DateTime(timezone=True), nullable=True)
                )
    bind = op.get_bind()
    for table in (
        CompanyDomain.__table__,
        DiscoveredURL.__table__,
        FetchError.__table__,
        JobObservation.__table__,
    ):
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in (
        JobObservation.__table__,
        FetchError.__table__,
        DiscoveredURL.__table__,
        CompanyDomain.__table__,
    ):
        table.drop(bind=bind, checkfirst=True)
    op.drop_column("research_sources", "last_changed_at")
    op.drop_column("research_sources", "last_fetched_at")
    op.drop_constraint("classification_confidence_range", "jobs", type_="check")
    op.drop_column("jobs", "classification_confidence")
    op.drop_index("ix_companies_normalized_name", table_name="companies")
    op.drop_column("companies", "normalized_name")
    op.create_unique_constraint(
        "uq_research_documents_source_id",
        "research_documents",
        ["source_id", "content_hash"],
    )
