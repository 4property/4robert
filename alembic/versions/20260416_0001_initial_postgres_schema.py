from __future__ import annotations

from alembic import op

from repositories.postgres.base import Base
from repositories.postgres import models as _models  # noqa: F401

revision = "20260416_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
