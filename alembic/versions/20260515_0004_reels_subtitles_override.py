"""Add ``reels.subtitles_override`` JSONB column (feature 36).

Per-reel subtitle override that pins the on-screen caption text and the
timing window for each cue. ``NULL`` is the canonical "no override —
fall back to the auto-generated captions (if ``autoCaptions`` is enabled)
or render no subtitles at all (if it is not)" sentinel. A non-null value
is an ordered JSON array of
``{"index": int, "text": str, "in_seconds": float, "out_seconds": float}``
entries whose ``index`` keys are unique and monotonically increasing, and
whose timing windows are non-overlapping with ``in_seconds >= 0`` and
``out_seconds > in_seconds``.

The override layer is purely editorial: it never replaces the source
caption pipeline, only swaps the rendered subtitle track when present.
The renderer falls back to the historical auto-captions flow when the
column is NULL, so an Alembic downgrade restores the previous behaviour
for every existing row without data loss.

Schema head before this migration: ``20260515_0003``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260515_0004"
down_revision = "20260515_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reels",
        sa.Column(
            "subtitles_override",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=None,
        ),
    )


def downgrade() -> None:
    op.drop_column("reels", "subtitles_override")
