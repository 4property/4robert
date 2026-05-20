"""Seed the ``galaxy`` render template row (feature 42).

Inserts a third active render template alongside ``classic`` and
``side_banner``:

- ``template_id``: ``galaxy``
- ``display_name``: ``Century 21``
- ``status``: ``active``
- ``sort_order``: 2 (after side_banner=1; classic stays at 0)
- ``layout_variant``: ``galaxy``

The layout variant is recognized by
``modules/rendering/infrastructure/render_template_settings.py:SUPPORTED_LAYOUT_VARIANTS``.
Downgrade removes the seeded row, but only if it is currently set to
the ``galaxy`` layout variant — i.e. it has not been manually edited
into a customized template — to avoid destroying user data on rollback.
"""

from __future__ import annotations

from alembic import op


revision = "20260518_0001"
down_revision = "20260517_0001"
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
            'galaxy',
            'Century 21',
            'Century 21 branded full-bleed photo with a rounded top-left info card, vertical status ribbon anchored on the right, and a rounded full-width agent/agency footer card.',
            'active',
            2,
            '[]'::jsonb,
            'galaxy',
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
        WHERE template_id = 'galaxy'
          AND layout_variant = 'galaxy'
        """
    )
