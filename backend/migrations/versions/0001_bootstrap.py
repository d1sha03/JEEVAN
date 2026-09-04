"""JEEVAN initial schema — all platform tables.

Revision ID: 0001_bootstrap
Revises:
Create Date: 2026-09-04
"""
from alembic import op

revision = "0001_bootstrap"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the full JEEVAN schema.

    The single source of truth is app.models.Base.metadata, matching the
    existing project convention. Subsequent revisions should be generated
    with `alembic revision --autogenerate` against the live database.
    """
    from app.database import Base
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from app.database import Base
    from app import models  # noqa: F401
    Base.metadata.drop_all(bind=op.get_bind())
