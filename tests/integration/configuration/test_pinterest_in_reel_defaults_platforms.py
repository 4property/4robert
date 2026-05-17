"""Integration tests for feature 19 — include ``pinterest`` in the default
``agency_reel_defaults.platforms`` array.

Covers three guarantees of migration ``20260514_0001``:

(a) After ``alembic upgrade head`` on a fresh schema, a row inserted
    into ``agency_reel_defaults`` without an explicit ``platforms``
    value picks up ``pinterest`` from the column's ``server_default``.

(b) The data migration appends ``pinterest`` to rows that pre-existed
    without it (simulated by writing the legacy 6-element array to a
    seeded row, then re-running the data-migration SQL idempotently).

(c) The data migration does **not** duplicate ``pinterest`` on rows
    that already contain it.

Tests (b) and (c) re-execute the data migration's SQL statement
directly against the schema rather than rolling Alembic back and
forward, because ``temporary_postgres_schema`` always upgrades to
``head`` before yielding. The statement is idempotent by design
(``WHERE NOT ('pinterest' = ANY(platforms))``), so re-running it
against a seeded row simulates the migration semantics faithfully.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from settings import DATABASE_URL
from tests.support.postgres import (
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


_EXPECTED_DEFAULT_PLATFORMS = [
    "tiktok",
    "instagram",
    "linkedin",
    "youtube",
    "facebook",
    "gbp",
    "pinterest",
]


_DATA_MIGRATION_SQL = (
    "UPDATE agency_reel_defaults "
    "SET platforms = array_append(platforms, 'pinterest') "
    "WHERE NOT ('pinterest' = ANY(platforms))"
)


def _insert_defaults_row(
    database_url: str,
    *,
    agency_id: str,
    platforms: list[str] | None,
) -> None:
    """Insert a row into ``agency_reel_defaults`` with explicit columns.

    When ``platforms is None`` the column is omitted so PostgreSQL
    applies the table-level ``server_default``.
    """
    timestamp = datetime.now(timezone.utc)
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            if platforms is None:
                connection.execute(
                    text(
                        "INSERT INTO agency_reel_defaults ("
                        "agency_id, duration_seconds, music_id, intro_enabled, "
                        "caption_template, render_template_id, settings, "
                        "created_at, updated_at"
                        ") VALUES ("
                        ":agency_id, 30, '', TRUE, '', 'classic', "
                        "'{}'::jsonb, :created_at, :updated_at"
                        ")"
                    ),
                    {
                        "agency_id": agency_id,
                        "created_at": timestamp,
                        "updated_at": timestamp,
                    },
                )
            else:
                connection.execute(
                    text(
                        "INSERT INTO agency_reel_defaults ("
                        "agency_id, platforms, duration_seconds, music_id, "
                        "intro_enabled, caption_template, render_template_id, "
                        "settings, created_at, updated_at"
                        ") VALUES ("
                        ":agency_id, :platforms, 30, '', TRUE, '', 'classic', "
                        "'{}'::jsonb, :created_at, :updated_at"
                        ")"
                    ),
                    {
                        "agency_id": agency_id,
                        "platforms": platforms,
                        "created_at": timestamp,
                        "updated_at": timestamp,
                    },
                )
    finally:
        engine.dispose()


def _fetch_platforms(database_url: str, agency_id: str) -> list[str]:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT platforms FROM agency_reel_defaults "
                    "WHERE agency_id = :agency_id"
                ),
                {"agency_id": agency_id},
            ).first()
    finally:
        engine.dispose()
    assert row is not None, f"agency_reel_defaults row missing for {agency_id}"
    return list(row.platforms or ())


def test_reel_defaults_server_default_includes_pinterest_after_migration() -> None:
    """A row created without an explicit ``platforms`` column inherits the
    canonical default — including ``pinterest`` — set by migration
    ``20260514_0001``."""
    with temporary_workspace():
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="pinterest-default.ie")
            _insert_defaults_row(
                database.url, agency_id=seeded.agency_id, platforms=None
            )
            assert _fetch_platforms(database.url, seeded.agency_id) == (
                _EXPECTED_DEFAULT_PLATFORMS
            )


def test_data_migration_adds_pinterest_to_existing_rows() -> None:
    """A row seeded with the pre-feature-19 6-element array gets
    ``pinterest`` appended when the data-migration SQL is replayed.
    Confirms the migration's idempotent ``WHERE`` clause picks up
    legacy rows."""
    legacy_platforms = [
        "tiktok",
        "instagram",
        "linkedin",
        "youtube",
        "facebook",
        "gbp",
    ]
    with temporary_workspace():
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="pinterest-backfill.ie")
            _insert_defaults_row(
                database.url,
                agency_id=seeded.agency_id,
                platforms=legacy_platforms,
            )
            # Pre-condition: row exists with the legacy array.
            assert _fetch_platforms(database.url, seeded.agency_id) == (
                legacy_platforms
            )

            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    connection.execute(text(_DATA_MIGRATION_SQL))
            finally:
                engine.dispose()

            assert _fetch_platforms(database.url, seeded.agency_id) == (
                legacy_platforms + ["pinterest"]
            )


def test_data_migration_preserves_existing_pinterest() -> None:
    """A row that already contains ``pinterest`` is left untouched —
    no duplicate is appended and the relative order is preserved."""
    platforms_with_pinterest = [
        "tiktok",
        "instagram",
        "linkedin",
        "youtube",
        "facebook",
        "gbp",
        "pinterest",
    ]
    with temporary_workspace():
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="pinterest-idempotent.ie")
            _insert_defaults_row(
                database.url,
                agency_id=seeded.agency_id,
                platforms=platforms_with_pinterest,
            )

            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    connection.execute(text(_DATA_MIGRATION_SQL))
            finally:
                engine.dispose()

            assert _fetch_platforms(database.url, seeded.agency_id) == (
                platforms_with_pinterest
            )
