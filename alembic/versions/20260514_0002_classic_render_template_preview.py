"""Attach the Classic render-template preview image."""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op


revision = "20260514_0002"
down_revision = "20260514_0001"
branch_labels = None
depends_on = None


_CLASSIC_PREVIEW_IMAGES = [
    {
        "kind": "preview",
        "image_url": "/assets/render-templates/classic-template.png",
        "alt": "Classic template preview",
    }
]


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE render_templates "
            "SET preview_images = CAST(:preview_images AS jsonb), "
            "updated_at = timezone('utc', now()) "
            "WHERE template_id = 'classic'"
        ).bindparams(preview_images=json.dumps(_CLASSIC_PREVIEW_IMAGES))
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE render_templates "
            "SET preview_images = '[]'::jsonb, "
            "updated_at = timezone('utc', now()) "
            "WHERE template_id = 'classic' "
            "AND preview_images = CAST(:preview_images AS jsonb)"
        ).bindparams(preview_images=json.dumps(_CLASSIC_PREVIEW_IMAGES))
    )
