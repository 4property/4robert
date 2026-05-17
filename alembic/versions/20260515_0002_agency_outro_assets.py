"""Create ``agency_intro_outro_assets`` table + ``outro_enabled`` flag.

Feature 33: each agency may upload a short MP4/MOV that the renderer
concatenates at the end of every reel. The asset metadata (object key,
duration in seconds, source kind) lives in a dedicated table because
feature 34 will reuse the exact same shape for the intro variant —
``kind`` is the discriminator (``'intro' | 'outro'``).

The on/off toggle stays on ``agency_reel_defaults`` so it mirrors the
existing ``intro_enabled`` column (which controls the auto-generated
intro card today). The migration is reversible: ``downgrade`` drops the
new table and column without touching pre-existing data.

The ``source`` column today only accepts ``'uploaded'`` or ``'none'``;
``'brand_card'`` is documented in the enum for forward compatibility
with a future auto-generated outro (out of scope for feature 33).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260515_0002"
down_revision = "20260515_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agency_reel_defaults",
        sa.Column(
            "outro_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_table(
        "agency_intro_outro_assets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "agency_id",
            sa.String(length=36),
            sa.ForeignKey("agencies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "source",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'none'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "agency_id",
            "kind",
            name="uq_agency_intro_outro_assets_agency_kind",
        ),
        sa.CheckConstraint(
            "kind IN ('intro', 'outro')",
            name="ck_agency_intro_outro_assets_kind",
        ),
        sa.CheckConstraint(
            "source IN ('uploaded', 'brand_card', 'none')",
            name="ck_agency_intro_outro_assets_source",
        ),
    )
    op.create_index(
        "idx_agency_intro_outro_assets_agency",
        "agency_intro_outro_assets",
        ["agency_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_agency_intro_outro_assets_agency",
        table_name="agency_intro_outro_assets",
    )
    op.drop_table("agency_intro_outro_assets")
    op.drop_column("agency_reel_defaults", "outro_enabled")
