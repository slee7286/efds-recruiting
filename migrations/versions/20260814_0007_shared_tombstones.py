"""Add shared sync tombstones.

Revision ID: 20260814_0007
Revises: 20260813_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260814_0007"
down_revision: str | None = "20260813_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The historical baseline creates the current model metadata for fresh
    # installs.  That means this additive migration may encounter the table
    # already present when upgrading a fresh database.  Older databases still
    # receive the table here.
    if inspect(op.get_bind()).has_table("shared_tombstones"):
        return
    op.create_table(
        "shared_tombstones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("collection", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.String(length=80), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("collection", "entity_id"),
    )


def downgrade() -> None:
    if inspect(op.get_bind()).has_table("shared_tombstones"):
        op.drop_table("shared_tombstones")
