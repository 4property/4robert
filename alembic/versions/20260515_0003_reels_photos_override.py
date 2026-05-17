"""Add ``reels.photos_override`` JSONB column (feature 35).

Per-reel photo override that pins the slide order and the per-slot
``selected`` flag. ``NULL`` is the canonical "no override — fall back to
the default order from the ``media_revisions`` / ``property_images``
positions" sentinel. A non-null value is an ordered JSON array of
``{"position": int, "selected": bool}`` entries whose ``position`` keys
cover the range ``[0, N)`` exactly once each, where ``N`` is the number
of source photos available for the property.

The override layer is purely editorial: it never replaces the source
photo set, only re-orders the slides and (optionally) drops some of
them from the rendered reel. The renderer falls back to the default
ordering when the column is NULL, so an Alembic downgrade restores the
historical behaviour for every existing row without data loss.

Schema head before this migration: ``20260515_0002``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260515_0003"
down_revision = "20260515_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reels",
        sa.Column(
            "photos_override",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=None,
        ),
    )


def downgrade() -> None:
    op.drop_column("reels", "photos_override")
