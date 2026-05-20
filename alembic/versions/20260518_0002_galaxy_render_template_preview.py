"""Attach the galaxy render-template preview image (feature 42).

Idempotent downgrade: only restores the empty array when the current
``preview_images`` value matches the payload this migration installed,
matching the convention from
``20260514_0002_classic_render_template_preview.py`` and
``20260515_0001_side_banner_render_template_preview.py``.
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op


revision = "20260518_0002"
down_revision = "20260518_0001"
branch_labels = None
depends_on = None


_GALAXY_PREVIEW_IMAGES = [
    {
        "kind": "preview",
        "image_url": "/assets/render-templates/galaxy-template.png",
        "alt": "Galaxy template preview",
    }
]


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE render_templates "
            "SET preview_images = CAST(:preview_images AS jsonb), "
            "updated_at = timezone('utc', now()) "
            "WHERE template_id = 'galaxy'"
        ).bindparams(preview_images=json.dumps(_GALAXY_PREVIEW_IMAGES))
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE render_templates "
            "SET preview_images = '[]'::jsonb, "
            "updated_at = timezone('utc', now()) "
            "WHERE template_id = 'galaxy' "
            "AND preview_images = CAST(:preview_images AS jsonb)"
        ).bindparams(preview_images=json.dumps(_GALAXY_PREVIEW_IMAGES))
    )
