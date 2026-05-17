"""Add ``reels.music_id`` per-reel music override column (feature 25).

When the editor wants to assign or change the background music for one
specific reel (rather than letting the agency pool resolver pick at
render time), the override is persisted as a nullable FK on the ``reels``
table. ``NULL`` is the canonical "no override — fall back to the agency
pool resolved by feature 23/24" sentinel; a non-null value points to a
row in ``agency_music_tracks`` that **must** belong to the same agency
as the reel (enforced by the use case, not by the FK itself — the FK
only guarantees referential integrity).

``ON DELETE SET NULL`` means that if the agency deletes the track after
the override was set, the column quietly resets to NULL and the next
render falls back to the agency pool. The worker also re-checks the
existence of the override id at render time (to handle the race where
the job was already enqueued with an ``override_music_track_id`` and the
track was deleted between the PATCH and the render).

The downgrade drops the FK then the column — no data preservation, the
override layer is purely editorial.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260514_0006"
down_revision = "20260514_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reels",
        sa.Column("music_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_reels_music_id_agency_music_tracks",
        "reels",
        "agency_music_tracks",
        ["music_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_reels_music_id_agency_music_tracks",
        "reels",
        type_="foreignkey",
    )
    op.drop_column("reels", "music_id")
