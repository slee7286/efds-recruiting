"""Create the complete V1 schema.

Revision ID: 20260812_0001
Revises:
"""

from alembic import op

from quant_recruiting.db import models  # noqa: F401
from quant_recruiting.db.base import Base

revision = "20260812_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The first revision is retained as the historical baseline. Current
    # models are created here so fresh installs have a valid dependency graph;
    # later revisions remain additive/idempotent for databases created from an
    # earlier V1/V2 checkout.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
