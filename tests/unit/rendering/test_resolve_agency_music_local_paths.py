"""Unit tests for the agency music pool resolver.

Feature 23 maps :class:`MusicTrack` rows to absolute :class:`Path` objects
that the renderer can feed to ffmpeg. The helper must:

* Translate a non-empty ``object_key`` into the matching path under
  ``workspace/generated_media/_agency_music/...``.
* Raise :class:`ResourceNotFoundError` with ``code="MUSIC_BLOB_MISSING"``
  when the blob is missing on disk or the ``object_key`` is empty.
* Reject :class:`MusicTrack` rows whose ``object_key`` carries an S3
  scheme (we never write those to disk).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.configuration.domain import MusicTrack
from modules.rendering.infrastructure.runtime.assets import (
    resolve_agency_music_local_paths,
)
from shared.errors import ResourceNotFoundError


def _build_track(*, object_key: str, music_id: str = "track-1") -> MusicTrack:
    return MusicTrack(
        music_id=music_id,
        agency_id="agency-1",
        display_name="Demo",
        object_key=object_key,
        duration_seconds=42,
        is_default=True,
        created_at="2026-05-14T00:00:00Z",
    )


def test_resolve_happy_path_returns_paths_in_order(tmp_path: Path) -> None:
    agency_dir = tmp_path / "generated_media" / "_agency_music" / "agency-1"
    agency_dir.mkdir(parents=True, exist_ok=True)
    (agency_dir / "a.mp3").write_bytes(b"a")
    (agency_dir / "b.mp3").write_bytes(b"b")
    tracks = (
        _build_track(object_key="agencies/agency-1/music/a.mp3", music_id="t-a"),
        _build_track(object_key="agencies/agency-1/music/b.mp3", music_id="t-b"),
    )

    resolved = resolve_agency_music_local_paths(
        workspace_dir=tmp_path,
        music_tracks=tracks,
    )

    assert resolved == (agency_dir / "a.mp3", agency_dir / "b.mp3")


def test_resolve_missing_blob_raises_music_blob_missing(tmp_path: Path) -> None:
    tracks = (
        _build_track(object_key="agencies/agency-1/music/missing.mp3"),
    )

    with pytest.raises(ResourceNotFoundError) as exc_info:
        resolve_agency_music_local_paths(
            workspace_dir=tmp_path,
            music_tracks=tracks,
        )

    assert exc_info.value.code == "MUSIC_BLOB_MISSING"


def test_resolve_empty_object_key_raises_music_blob_missing(tmp_path: Path) -> None:
    tracks = (_build_track(object_key=""),)

    with pytest.raises(ResourceNotFoundError) as exc_info:
        resolve_agency_music_local_paths(
            workspace_dir=tmp_path,
            music_tracks=tracks,
        )

    assert exc_info.value.code == "MUSIC_BLOB_MISSING"


def test_resolve_rejects_object_key_with_scheme(tmp_path: Path) -> None:
    tracks = (
        _build_track(object_key="s3://bucket/agencies/agency-1/music/x.mp3"),
    )

    with pytest.raises(ResourceNotFoundError) as exc_info:
        resolve_agency_music_local_paths(
            workspace_dir=tmp_path,
            music_tracks=tracks,
        )

    assert exc_info.value.code == "MUSIC_BLOB_MISSING"


def test_resolve_returns_empty_tuple_for_empty_input(tmp_path: Path) -> None:
    assert (
        resolve_agency_music_local_paths(
            workspace_dir=tmp_path,
            music_tracks=(),
        )
        == ()
    )
