from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260429_0003"
down_revision = "20260428_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("idx_gohighlevel_tokens_user_id", table_name="gohighlevel_tokens")
    op.drop_table("gohighlevel_tokens")

    op.create_table(
        "ghl_connections",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "agency_id",
            sa.String(length=36),
            sa.ForeignKey("agencies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("location_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("user_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("access_token", sa.Text(), nullable=False, server_default=""),
        sa.Column("refresh_token", sa.Text(), nullable=False, server_default=""),
        sa.Column("expires_at", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("agency_id", name="uq_ghl_connections_agency_id"),
    )
    op.create_index(
        "idx_ghl_connections_location_id",
        "ghl_connections",
        ["location_id"],
    )

    op.create_table(
        "reel_profiles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "agency_id",
            sa.String(length=36),
            sa.ForeignKey("agencies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False, server_default="Default"),
        sa.Column(
            "platforms_json",
            sa.Text(),
            nullable=False,
            server_default='["tiktok","instagram","linkedin","youtube","facebook","gbp"]',
        ),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("music_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("intro_enabled", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("logo_position", sa.Text(), nullable=False, server_default="top-right"),
        sa.Column("brand_primary_color", sa.Text(), nullable=False, server_default="#0F172A"),
        sa.Column("brand_secondary_color", sa.Text(), nullable=False, server_default="#FFFFFF"),
        sa.Column("caption_template", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "approval_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column("extra_settings_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("agency_id", name="uq_reel_profiles_agency_id"),
    )


def downgrade() -> None:
    op.drop_table("reel_profiles")
    op.drop_index("idx_ghl_connections_location_id", table_name="ghl_connections")
    op.drop_table("ghl_connections")

    op.create_table(
        "gohighlevel_tokens",
        sa.Column("location_id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=False, server_default=""),
        sa.Column("expires_at", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index(
        "idx_gohighlevel_tokens_user_id",
        "gohighlevel_tokens",
        ["user_id"],
    )
