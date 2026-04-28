from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260428_0002"
down_revision = "20260416_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_index("idx_gohighlevel_tokens_user_id", table_name="gohighlevel_tokens")
    op.drop_table("gohighlevel_tokens")
