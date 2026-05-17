"""Add ``pinterest`` to the canonical default of ``agency_reel_defaults.platforms``.

Feature 7 made Pinterest a connectable + publishable social destination,
and the frontend already exposes it in ``/social`` and ``/defaults``. The
application-layer fallback in
``modules.configuration.application.use_cases.read_aggregated_reel_profile``
and ``modules.configuration.transport.http.defaults_router`` already
includes ``pinterest`` in the ``_DEFAULT_PLATFORMS`` tuple, but the
**database** ``server_default`` baked into the initial migration
(``20260501_0001_initial_schema.py``) is still::

    ARRAY['tiktok','instagram','linkedin','youtube','facebook','gbp']::text[]

so a row created with an explicit INSERT that omits ``platforms`` does
not get Pinterest. More importantly, agencies that pre-existed are
sitting on rows that never had Pinterest at all — once they configure
the Pinterest social template via ``/social`` their reels never receive
captions for it because ``agency_reel_defaults.platforms`` (the
canonical owner) excludes it.

This migration does two things:

1. ``ALTER COLUMN ... SET DEFAULT`` flips the server default of
   ``agency_reel_defaults.platforms`` to the full seven-element array
   including ``pinterest``. The column type is the native
   PostgreSQL ``text[]`` (``ARRAY(Text)``), so the SQL is::

       ARRAY['tiktok','instagram','linkedin','youtube','facebook','gbp','pinterest']::text[]

2. A non-destructive data migration appends ``'pinterest'`` to every
   existing row that does not already contain it, using PostgreSQL's
   ``array_append``. Rows that already had ``pinterest`` (set via PUT
   /defaults or future test seeds) are left untouched.

``downgrade()`` reverts the ``server_default`` to the pre-feature value.
It deliberately does **not** strip ``pinterest`` from existing rows:
those values represent agency configuration that the operator intended
to keep, and re-emitting captions to platforms the agency configured is
not destructive. Stripping them would silently lose user intent if this
migration is rolled forward and back during a deployment. The downgrade
keeps the door open to re-applying the upgrade idempotently.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260514_0001"
down_revision = "20260513_0005"
branch_labels = None
depends_on = None


_NEW_DEFAULT_SQL = (
    "ARRAY['tiktok','instagram','linkedin','youtube','facebook','gbp','pinterest']::text[]"
)
_OLD_DEFAULT_SQL = (
    "ARRAY['tiktok','instagram','linkedin','youtube','facebook','gbp']::text[]"
)


def upgrade() -> None:
    op.alter_column(
        "agency_reel_defaults",
        "platforms",
        server_default=sa.text(_NEW_DEFAULT_SQL),
    )
    # Data migration: append 'pinterest' to rows that do not already
    # contain it. ``array_append`` is the canonical PG operator for this
    # and is safe on NULL-free ``text[]`` columns (the schema marks
    # ``platforms`` as ``NOT NULL`` with a non-null default, so every
    # row already has an array).
    op.execute(
        sa.text(
            "UPDATE agency_reel_defaults "
            "SET platforms = array_append(platforms, 'pinterest') "
            "WHERE NOT ('pinterest' = ANY(platforms))"
        )
    )


def downgrade() -> None:
    op.alter_column(
        "agency_reel_defaults",
        "platforms",
        server_default=sa.text(_OLD_DEFAULT_SQL),
    )
    # Intentionally NOT stripping 'pinterest' from existing rows — see
    # the module docstring for the rationale.
