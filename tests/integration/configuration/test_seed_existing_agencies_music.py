"""Integration tests for Feature 23 — seed default NCS music tracks.

Covers the three guarantees of migration ``20260514_0005``:

(a) After ``alembic upgrade head`` on a fresh schema with at least one
    agency present at upgrade time, that agency owns N rows in
    ``agency_music_tracks`` (``is_default=true``) and N blobs on disk
    under ``workspace/generated_media/_agency_music/<agency>/``.

(b) ``alembic downgrade -1`` removes every row whose ``object_key``
    matches the seed marker AND the matching on-disk blobs, while a
    user-uploaded track (different ``object_key`` shape) survives.

(c) Re-running ``alembic upgrade head`` after a partial seed (e.g. an
    agency the admin added manually after the first run) only seeds
    the agencies that still lack any tracks — never overwriting custom
    uploads or duplicating seed rows.

Test (a) uses :func:`seed_tenant` to insert an agency before yielding
the schema, but :func:`temporary_postgres_schema` always upgrades
before any user code runs — so the migration runs on an empty
``agencies`` table. To prove the per-agency seed, we manually re-run
the migration's data path against agencies inserted after head, which
is the exact code-path the ``RegisterAgencyUseCase`` hook exercises in
:mod:`tests.integration.tenancy.test_admin_agencies_router`.

Tests (b) and (c) exercise the migration directly via subprocess to
match the production semantics.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text

from settings import DATABASE_URL
from tests.support.postgres import (
    APPLICATION_ROOT,
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


def _insert_agency(database_url: str, *, name: str) -> str:
    """Insert an agency row directly (bypasses the use case seed hook)."""
    agency_id = str(uuid4())
    timestamp = datetime.now(timezone.utc)
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO agencies (id, name, slug, timezone, status, "
                    "created_at, updated_at) VALUES (:id, :name, :slug, "
                    ":timezone, :status, :created_at, :updated_at)"
                ),
                {
                    "id": agency_id,
                    "name": name,
                    "slug": f"{name.lower().replace(' ', '-')}-{agency_id[:6]}",
                    "timezone": "Europe/Dublin",
                    "status": "active",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            )
    finally:
        engine.dispose()
    return agency_id


def _run_alembic(workspace_dir: Path, database_url: str, *args: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["REELS_WORKSPACE_DIR"] = str(workspace_dir)
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=APPLICATION_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"alembic {' '.join(args)} failed.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )


def _list_tracks(database_url: str, agency_id: str) -> list[tuple[str, str, bool]]:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT display_name, object_key, is_default "
                    "FROM agency_music_tracks WHERE agency_id = :agency_id "
                    "ORDER BY display_name ASC"
                ),
                {"agency_id": agency_id},
            ).all()
    finally:
        engine.dispose()
    return [(row.display_name, row.object_key, bool(row.is_default)) for row in rows]


def test_seed_migration_backfills_existing_agency_after_replay() -> None:
    """An agency that exists at the moment the seed migration runs ends
    up with the canonical pool of NCS tracks on disk and in the DB."""
    from modules.configuration.domain import DEFAULT_NCS_MUSIC_TRACK_SEEDS

    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            agency_id = _insert_agency(database.url, name="Pre-migration Agency")

            # The schema is already at head, so the seed migration ran on
            # an empty agencies table. Re-apply the migration manually by
            # downgrading to the revision *before* the seed and then
            # upgrading to head — exercises the data path. We name the
            # target revision explicitly so this test keeps working as
            # new migrations stack on top of the seed.
            _run_alembic(workspace_dir, database.url, "downgrade", "20260514_0004")
            _run_alembic(workspace_dir, database.url, "upgrade", "head")

            tracks = _list_tracks(database.url, agency_id)
            assert len(tracks) == len(DEFAULT_NCS_MUSIC_TRACK_SEEDS)
            expected_names = sorted(seed.display_name for seed in DEFAULT_NCS_MUSIC_TRACK_SEEDS)
            assert [name for name, _key, _default in tracks] == expected_names
            for _name, object_key, is_default in tracks:
                assert is_default is True
                assert object_key.startswith(f"agencies/{agency_id}/music/_seed_ncs_")

            music_dir = (
                workspace_dir
                / "generated_media"
                / "_agency_music"
                / agency_id
            )
            assert music_dir.is_dir()
            blobs = sorted(p.name for p in music_dir.iterdir())
            expected_blobs = sorted(
                seed.destination_filename for seed in DEFAULT_NCS_MUSIC_TRACK_SEEDS
            )
            assert blobs == expected_blobs
            for blob_name in blobs:
                assert (music_dir / blob_name).stat().st_size > 0


def test_seed_migration_downgrade_only_removes_seeded_rows() -> None:
    """Downgrade clears rows that match the ``_seed_ncs_`` marker but
    leaves user-uploaded rows (different ``object_key`` shape) intact."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            agency_id = _insert_agency(database.url, name="Mixed Library Agency")

            # Re-apply the seed migration on top of the pre-seed
            # revision so the agency picks up the canonical NCS pool.
            _run_alembic(workspace_dir, database.url, "downgrade", "20260514_0004")
            _run_alembic(workspace_dir, database.url, "upgrade", "head")

            # The agency now has 4 seeded tracks. Drop a fake "user upload"
            # alongside them; the downgrade must keep it.
            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO agency_music_tracks ("
                            "id, agency_id, display_name, object_key, "
                            "duration_seconds, is_default, created_at"
                            ") VALUES (:id, :agency_id, :display_name, "
                            ":object_key, :duration_seconds, :is_default, "
                            ":created_at)"
                        ),
                        {
                            "id": str(uuid4()),
                            "agency_id": agency_id,
                            "display_name": "User Upload",
                            "object_key": (
                                f"agencies/{agency_id}/music/user_upload.mp3"
                            ),
                            "duration_seconds": 99,
                            "is_default": False,
                            "created_at": datetime.now(timezone.utc),
                        },
                    )
            finally:
                engine.dispose()

            assert len(_list_tracks(database.url, agency_id)) == 5

            # Downgrade explicitly to the pre-seed revision so the seed
            # migration's downgrade path runs. ``-1`` would only roll
            # back the most recent migration (e.g. feature 25's
            # ``reels.music_id`` column) and leave the seed rows in
            # place.
            _run_alembic(workspace_dir, database.url, "downgrade", "20260514_0004")

            remaining = _list_tracks(database.url, agency_id)
            assert len(remaining) == 1
            assert remaining[0][0] == "User Upload"
            assert remaining[0][1].endswith("/user_upload.mp3")


def test_seed_migration_skips_agencies_with_existing_tracks() -> None:
    """An agency that already owns tracks (e.g. user uploaded one
    before the migration ran) is skipped — no duplicate seed rows."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            agency_id = _insert_agency(database.url, name="Pre-seeded Agency")

            # Seed one user-track manually BEFORE the seed migration
            # runs. We downgrade to the revision just below the seed
            # migration (named explicitly so this stays correct as new
            # migrations stack on top).
            _run_alembic(workspace_dir, database.url, "downgrade", "20260514_0004")
            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO agency_music_tracks ("
                            "id, agency_id, display_name, object_key, "
                            "duration_seconds, is_default, created_at"
                            ") VALUES (:id, :agency_id, :display_name, "
                            ":object_key, :duration_seconds, :is_default, "
                            ":created_at)"
                        ),
                        {
                            "id": str(uuid4()),
                            "agency_id": agency_id,
                            "display_name": "Solo Custom",
                            "object_key": (
                                f"agencies/{agency_id}/music/solo_custom.mp3"
                            ),
                            "duration_seconds": 33,
                            "is_default": False,
                            "created_at": datetime.now(timezone.utc),
                        },
                    )
            finally:
                engine.dispose()

            _run_alembic(workspace_dir, database.url, "upgrade", "head")

            tracks = _list_tracks(database.url, agency_id)
            assert len(tracks) == 1
            assert tracks[0][0] == "Solo Custom"
