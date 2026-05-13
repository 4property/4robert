"""Extend ``agency_automation_rules`` with hold_window/quiet_hours/skip_weekends.

Adds three backward-compatible columns to ``agency_automation_rules`` so
the publish-scheduler can honour:

- ``hold_window_seconds`` (``INTEGER NOT NULL DEFAULT 0``): delay applied
  before the publish slot is computed, capped to 24h at the payload
  layer. ``0`` preserves the pre-feature-13 "immediate" behaviour.
- ``quiet_hours_enabled`` (``BOOLEAN NOT NULL DEFAULT FALSE``): when
  ``TRUE``, publishes scheduled outside ``[publish_window_start,
  publish_window_end]`` are deferred to the next ``publish_window_start``
  (the algorithm itself lands in feature 14).
- ``skip_weekends`` (``BOOLEAN NOT NULL DEFAULT FALSE``): when ``TRUE``,
  Saturday/Sunday slots are deferred to the next Monday.

``server_default`` guarantees existing rows survive ``UPGRADE`` without
backfill. The PUT payload (``AutomationRulesUpsertPayload``) accepts the
three fields as optional; the repository preserves the previous value
when a PUT omits any of them, so the new contract stays additive.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260513_0005"
down_revision = "20260513_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agency_automation_rules",
        sa.Column(
            "hold_window_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "agency_automation_rules",
        sa.Column(
            "quiet_hours_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.add_column(
        "agency_automation_rules",
        sa.Column(
            "skip_weekends",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )


def downgrade() -> None:
    op.drop_column("agency_automation_rules", "skip_weekends")
    op.drop_column("agency_automation_rules", "quiet_hours_enabled")
    op.drop_column("agency_automation_rules", "hold_window_seconds")
