"""Add ``reels.descriptions_override`` JSONB column (feature 21).

Per-reel description override that wins over the inert
``publish_target_snapshot.descriptions_by_platform`` at publish time. The
column is nullable and defaults to ``NULL`` so existing rows remain
unaffected and only reels that have been explicitly edited via the
``PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/descriptions``
endpoint carry a value.

The reverse migration drops the column without preserving the data —
overrides are an editorial convenience layer (the snapshot still holds
the templated captions), so a downgrade in a deployment window is
acceptable.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260514_0003"
down_revision = "20260514_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reels",
        sa.Column(
            "descriptions_override",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=None,
        ),
    )


def downgrade() -> None:
    op.drop_column("reels", "descriptions_override")
