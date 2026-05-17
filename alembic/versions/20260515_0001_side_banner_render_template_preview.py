"""Attach the side_banner render-template preview image."""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op


revision = "20260515_0001"
down_revision = "20260514_0007"
branch_labels = None
depends_on = None


_SIDE_BANNER_PREVIEW_IMAGES = [
    {
        "kind": "preview",
        "image_url": "/assets/render-templates/side-banner-template.png",
        "alt": "Side banner template preview",
    }
]


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE render_templates "
            "SET preview_images = CAST(:preview_images AS jsonb), "
            "updated_at = timezone('utc', now()) "
            "WHERE template_id = 'side_banner'"
        ).bindparams(preview_images=json.dumps(_SIDE_BANNER_PREVIEW_IMAGES))
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE render_templates "
            "SET preview_images = '[]'::jsonb, "
            "updated_at = timezone('utc', now()) "
            "WHERE template_id = 'side_banner' "
            "AND preview_images = CAST(:preview_images AS jsonb)"
        ).bindparams(preview_images=json.dumps(_SIDE_BANNER_PREVIEW_IMAGES))
    )
