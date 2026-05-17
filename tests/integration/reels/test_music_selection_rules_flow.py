"""Integration tests for the music selection rules flow (Feature 24).

These tests exercise the end-to-end wiring between the persisted
``agency_reel_defaults.settings.music.selection_rules.fallback_to_full_library``
flag and the renderer's audio-pool resolution:

* When the agency default pool is empty and the flag is ``True``
  (or absent — same as ``True`` per the documented default) the resolver
  falls back to the full library.
* When the same agency flips the flag to ``False`` the resolver raises
  ``PropertyReelError`` with code ``MUSIC_NO_DEFAULT_TRACKS`` so the
  reel pipeline fails loudly instead of silently using a non-default
  track.
* When the agency has at least one default track the flag does not
  matter — the resolver always uses the default pool.

The tests use the real ``IngestPropertyIntoReelUseCase`` against a
Postgres schema so they cover the wiring through the use case
(reading defaults.settings, forwarding the flag) instead of just the
free-function ``resolve_agency_background_audio_candidates``. The
seeded music tracks point at on-disk blobs under the workspace
``_agency_music`` folder so the resolver can produce a non-empty
``background_audio_candidates`` tuple.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from modules.reels.application.use_cases.ingest_property_into_reel import (
    IngestPropertyIntoReelUseCase,
)
from modules.reels.domain.types import PropertyMediaJob
from modules.tenancy.domain.context import TenantContext
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from shared.errors import PropertyReelError
from tests.support.postgres import (
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


_PAYLOAD = {
    "id": 99,
    "slug": "music-rules-flow",
    "title": {"rendered": "Music rules flow"},
    "link": "https://ckp.ie/music-rules-flow",
    "property_status": "for sale",
    "price": "275000",
    "wppd_pics": ["https://ckp.ie/img1.jpg"],
}


def _build_job(*, agency_id: str, ingestion_source_id: str, site_id: str) -> PropertyMediaJob:
    tenant = TenantContext(
        site_id=site_id,
        agency_id=agency_id,
        wordpress_source_id=ingestion_source_id,
    )
    return PropertyMediaJob(
        event_id="event-music-rules",
        tenant=tenant,
        property_id=99,
        received_at="2026-05-14T10:00:00+00:00",
        raw_payload_hash="hash-music-rules",
        payload=_PAYLOAD,
        publish_context=None,
        job_id="job-music-rules",
    )


def _write_track_blob(
    *,
    workspace_dir: Path,
    agency_id: str,
    filename: str,
) -> str:
    """Write a stub MP3 under the agency music dir and return the object key."""
    music_dir = (
        workspace_dir / "generated_media" / "_agency_music" / agency_id
    )
    music_dir.mkdir(parents=True, exist_ok=True)
    (music_dir / filename).write_bytes(b"stub-mp3-bytes")
    return f"agencies/{agency_id}/music/{filename}"


def _insert_music_track(
    *,
    database_url: str,
    agency_id: str,
    object_key: str,
    is_default: bool,
    display_name: str,
) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO agency_music_tracks ("
                    "id, agency_id, display_name, object_key, "
                    "duration_seconds, is_default, created_at"
                    ") VALUES (:id, :agency_id, :display_name, "
                    ":object_key, :duration_seconds, :is_default, NOW())"
                ),
                {
                    "id": str(uuid4()),
                    "agency_id": agency_id,
                    "display_name": display_name,
                    "object_key": object_key,
                    "duration_seconds": 42,
                    "is_default": is_default,
                },
            )
    finally:
        engine.dispose()


def _persist_music_flag(
    *,
    database_url: str,
    workspace_dir: Path,
    agency_id: str,
    fallback_to_full_library: bool,
) -> None:
    """Set ``settings.music.selection_rules.fallback_to_full_library``."""
    with DatabaseUnitOfWork(database_url, workspace_dir) as uow:
        assert uow.configuration is not None
        uow.configuration.defaults.upsert(
            agency_id=agency_id,
            settings={
                "music": {
                    "selection_rules": {
                        "fallback_to_full_library": fallback_to_full_library,
                    }
                }
            },
        )


def test_ingest_uses_library_when_fallback_true_and_no_defaults() -> None:
    """Empty default pool + flag absent (default True) → library is used."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            # ``seed_default_music=False`` skips the seeded default
            # track so we can hand-roll a library-only pool.
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                seed_default_music=False,
                workspace_dir=workspace_dir,
            )
            library_object_key = _write_track_blob(
                workspace_dir=workspace_dir,
                agency_id=seeded.agency_id,
                filename="library.mp3",
            )
            _insert_music_track(
                database_url=database.url,
                agency_id=seeded.agency_id,
                object_key=library_object_key,
                is_default=False,
                display_name="Library Track",
            )

            use_case = IngestPropertyIntoReelUseCase(
                workspace_dir=workspace_dir,
                property_url_template="",
                property_url_tracking_params=None,
                social_publishing_enabled=False,
                database_locator=database.url,
            )

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                context = use_case.execute(
                    _build_job(
                        agency_id=seeded.agency_id,
                        ingestion_source_id=seeded.ingestion_source_id,
                        site_id=seeded.external_source_id,
                    ),
                    uow=uow,
                )

            assert len(context.background_audio_candidates) == 1
            assert (
                context.background_audio_candidates[0].name == "library.mp3"
            )


def test_ingest_raises_when_fallback_false_and_no_defaults() -> None:
    """Empty default pool + flag=False → ``MUSIC_NO_DEFAULT_TRACKS``."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                seed_default_music=False,
                workspace_dir=workspace_dir,
            )
            library_object_key = _write_track_blob(
                workspace_dir=workspace_dir,
                agency_id=seeded.agency_id,
                filename="library.mp3",
            )
            _insert_music_track(
                database_url=database.url,
                agency_id=seeded.agency_id,
                object_key=library_object_key,
                is_default=False,
                display_name="Library Track",
            )
            _persist_music_flag(
                database_url=database.url,
                workspace_dir=workspace_dir,
                agency_id=seeded.agency_id,
                fallback_to_full_library=False,
            )

            use_case = IngestPropertyIntoReelUseCase(
                workspace_dir=workspace_dir,
                property_url_template="",
                property_url_tracking_params=None,
                social_publishing_enabled=False,
                database_locator=database.url,
            )

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                with pytest.raises(PropertyReelError) as exc_info:
                    use_case.execute(
                        _build_job(
                            agency_id=seeded.agency_id,
                            ingestion_source_id=seeded.ingestion_source_id,
                            site_id=seeded.external_source_id,
                        ),
                        uow=uow,
                    )

            assert exc_info.value.code == "MUSIC_NO_DEFAULT_TRACKS"


def test_ingest_uses_default_pool_regardless_of_flag() -> None:
    """Non-empty default pool → flag does not matter, default pool wins."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                seed_default_music=False,
                workspace_dir=workspace_dir,
            )
            default_object_key = _write_track_blob(
                workspace_dir=workspace_dir,
                agency_id=seeded.agency_id,
                filename="default.mp3",
            )
            library_object_key = _write_track_blob(
                workspace_dir=workspace_dir,
                agency_id=seeded.agency_id,
                filename="library.mp3",
            )
            _insert_music_track(
                database_url=database.url,
                agency_id=seeded.agency_id,
                object_key=default_object_key,
                is_default=True,
                display_name="Default Track",
            )
            _insert_music_track(
                database_url=database.url,
                agency_id=seeded.agency_id,
                object_key=library_object_key,
                is_default=False,
                display_name="Library Track",
            )
            _persist_music_flag(
                database_url=database.url,
                workspace_dir=workspace_dir,
                agency_id=seeded.agency_id,
                fallback_to_full_library=False,
            )

            use_case = IngestPropertyIntoReelUseCase(
                workspace_dir=workspace_dir,
                property_url_template="",
                property_url_tracking_params=None,
                social_publishing_enabled=False,
                database_locator=database.url,
            )

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                context = use_case.execute(
                    _build_job(
                        agency_id=seeded.agency_id,
                        ingestion_source_id=seeded.ingestion_source_id,
                        site_id=seeded.external_source_id,
                    ),
                    uow=uow,
                )

            assert len(context.background_audio_candidates) == 1
            assert (
                context.background_audio_candidates[0].name == "default.mp3"
            )
