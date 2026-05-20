"""Add ``reels.auto_subtitles_snapshot`` JSONB column (feature 41).

Per-reel snapshot of the cues the autoCaptions pipeline (Gemini → caption
per slide → timing window) produces at render time. ``NULL`` is the
canonical "no snapshot yet — the reel was never rendered, or the last
render ran with a ``subtitles_override`` set so the snapshot from the
previous run is still authoritative" sentinel. A non-null value is an
ordered JSON array of
``{"index": int, "text": str, "in_seconds": float, "out_seconds": float}``
entries — the same shape ``reels.subtitles_override`` uses, so the
editor can swap one for the other without translation.

Feature 36 lets the editor PATCH ``subtitles_override``. Feature 41 makes
sure the editor has a starting value: the snapshot is refreshed on every
render whose ``subtitles_override`` is NULL (the Gemini cues are visible
to the rendering pipeline at that moment, but never persisted today),
and preserved untouched on every render whose ``subtitles_override`` is
not NULL (the autoCaptions pipeline does not run, so the previous
snapshot is still the right "starting value" if the editor clears the
override).

Schema head before this migration: ``20260515_0005``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260517_0001"
down_revision = "20260515_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reels",
        sa.Column(
            "auto_subtitles_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=None,
        ),
    )


def downgrade() -> None:
    op.drop_column("reels", "auto_subtitles_snapshot")
