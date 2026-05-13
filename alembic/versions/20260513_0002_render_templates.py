"""Add DB-backed render template catalog."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg


revision = "20260513_0002"
down_revision = "20260501_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "render_templates",
        sa.Column("template_id", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "preview_images",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("layout_variant", sa.Text(), nullable=False, server_default="classic"),
        sa.Column(
            "reel_settings",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "poster_settings",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(
        """
        INSERT INTO render_templates (
            template_id, display_name, description, status, sort_order,
            preview_images, layout_variant, reel_settings, poster_settings,
            created_at, updated_at
        ) VALUES (
            'classic',
            'Classic',
            'The original 4Reels renderer layout and settings.',
            'active',
            0,
            '[]'::jsonb,
            'classic',
            '{}'::jsonb,
            '{}'::jsonb,
            timezone('utc', now()),
            timezone('utc', now())
        ) ON CONFLICT (template_id) DO NOTHING
        """
    )

    op.add_column(
        "agency_reel_defaults",
        sa.Column(
            "render_template_id",
            sa.Text(),
            nullable=False,
            server_default="classic",
        ),
    )
    op.create_foreign_key(
        "fk_agency_reel_defaults_render_template_id",
        "agency_reel_defaults",
        "render_templates",
        ["render_template_id"],
        ["template_id"],
    )

    op.add_column(
        "reels",
        sa.Column(
            "render_template_id",
            sa.Text(),
            nullable=False,
            server_default="classic",
        ),
    )
    op.create_foreign_key(
        "fk_reels_render_template_id",
        "reels",
        "render_templates",
        ["render_template_id"],
        ["template_id"],
    )

    op.add_column(
        "media_revisions",
        sa.Column(
            "render_template_id",
            sa.Text(),
            nullable=False,
            server_default="classic",
        ),
    )
    op.create_foreign_key(
        "fk_media_revisions_render_template_id",
        "media_revisions",
        "render_templates",
        ["render_template_id"],
        ["template_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_media_revisions_render_template_id",
        "media_revisions",
        type_="foreignkey",
    )
    op.drop_column("media_revisions", "render_template_id")
    op.drop_constraint("fk_reels_render_template_id", "reels", type_="foreignkey")
    op.drop_column("reels", "render_template_id")
    op.drop_constraint(
        "fk_agency_reel_defaults_render_template_id",
        "agency_reel_defaults",
        type_="foreignkey",
    )
    op.drop_column("agency_reel_defaults", "render_template_id")
    op.drop_table("render_templates")
