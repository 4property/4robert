"""Add ``reels.manifest_override`` JSONB column (feature 37).

Per-reel slide manifest override that lets an admin edit the scene list
(order, duration, kind, kind-specific fields) before the reel is rendered.
``NULL`` is the canonical "no override — fall back to the auto-generated
manifest pipeline" sentinel. A non-null value is an ordered JSON array of
``{"slide_id", "position", "duration_seconds", "kind", ...kind-specific}``
entries whose ``position`` keys cover the range ``[0, N)`` exactly once,
whose ``slide_id`` values are unique non-empty strings, whose
``duration_seconds`` are positive floats summing to at most ``1.5 *
target_duration_seconds``, and whose ``kind`` discriminator is one of
``{"photo", "voiceover", "text", "intro_card", "outro_card"}``.

The override layer is editorial: it never replaces the source material,
only swaps the scene list the renderer consumes. The renderer falls
back to the historical auto-generated pipeline when the column is NULL,
so an Alembic downgrade restores the previous behaviour for every
existing row without data loss.

Schema head before this migration: ``20260515_0004``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260515_0005"
down_revision = "20260515_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reels",
        sa.Column(
            "manifest_override",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=None,
        ),
    )


def downgrade() -> None:
    op.drop_column("reels", "manifest_override")
