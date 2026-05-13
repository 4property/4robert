"""Seed the ``side_banner`` render template row.

Inserts a second active render template alongside ``classic``:

- ``template_id``: ``side_banner``
- ``display_name``: ``Side Banner``
- ``status``: ``active``
- ``sort_order``: 1 (classic stays at 0 so it lists first by default)
- ``layout_variant``: ``side_banner``

The layout variant is recognized by
``modules/rendering/infrastructure/render_template_settings.py:SUPPORTED_LAYOUT_VARIANTS``.
Downgrade removes the seeded row, but only if it is currently set to the
``side_banner`` layout variant — i.e. it has not been manually edited
into a customized template — to avoid destroying user data on rollback.
"""

from __future__ import annotations

from alembic import op


revision = "20260513_0004"
down_revision = "20260513_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO render_templates (
            template_id, display_name, description, status, sort_order,
            preview_images, layout_variant, reel_settings, poster_settings,
            created_at, updated_at
        ) VALUES (
            'side_banner',
            'Side Banner',
            'Full-bleed photo with a top-left info panel, vertical status banner anchored on the right, and full-width agent/agency footer.',
            'active',
            1,
            '[]'::jsonb,
            'side_banner',
            '{}'::jsonb,
            '{}'::jsonb,
            timezone('utc', now()),
            timezone('utc', now())
        ) ON CONFLICT (template_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM render_templates
        WHERE template_id = 'side_banner'
          AND layout_variant = 'side_banner'
        """
    )
