"""Rename the galaxy render template to Century 21.

The template_id/layout_variant remain ``galaxy`` for backwards-compatible
selection and renderer dispatch. Only the user-facing ``display_name`` changes.
"""

from __future__ import annotations

from alembic import op


revision = "20260519_0001"
down_revision = "20260518_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE render_templates
        SET display_name = 'Century 21',
            description = 'Century 21 branded full-bleed photo with a rounded top-left info card, vertical status ribbon anchored on the right, and a rounded full-width agent/agency footer card.',
            updated_at = timezone('utc', now())
        WHERE template_id = 'galaxy'
          AND layout_variant = 'galaxy'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE render_templates
        SET display_name = 'Galaxy',
            description = 'Full-bleed photo with a rounded top-left info card, vertical status ribbon anchored on the right, and a rounded full-width agent/agency footer card.',
            updated_at = timezone('utc', now())
        WHERE template_id = 'galaxy'
          AND layout_variant = 'galaxy'
          AND display_name = 'Century 21'
        """
    )
