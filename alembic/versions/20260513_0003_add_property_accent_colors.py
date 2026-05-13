"""Add property accent colors columns for the side_banner render template.

Adds two nullable Text columns to ``properties``:

- ``wppd_accent_text_color``: HEX string for accent text color (e.g. text
  inside the top/bottom panels of the side_banner layout).
- ``wppd_accent_background_color``: HEX string for the accent panel
  background color (applied with alpha overlay at render time).

Both columns are populated from the WordPress webhook payload
(``wppd_accent_*`` keys) during ingestion. They default to ``NULL`` when
the webhook omits them, in which case the renderer falls back to
``BrandSettings.primary_color`` of the agency.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260513_0003"
down_revision = "20260513_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "properties",
        sa.Column("wppd_accent_text_color", sa.Text(), nullable=True),
    )
    op.add_column(
        "properties",
        sa.Column("wppd_accent_background_color", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("properties", "wppd_accent_background_color")
    op.drop_column("properties", "wppd_accent_text_color")
