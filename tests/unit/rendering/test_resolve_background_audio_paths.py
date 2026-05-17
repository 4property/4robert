"""Unit tests for :func:`resolve_background_audio_paths` (Feature 23).

The function now accepts an explicit ``music_tracks`` tuple resolved
by the upstream use case from the agency music pool. The legacy scan
of ``workspace/<assets>/music/`` survives as a fallback for readiness
and dev flows without a database (``music_tracks=None``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.rendering.infrastructure.models import PropertyReelTemplate
from modules.rendering.infrastructure.runtime.assets import (
    resolve_background_audio_paths,
)
from shared.errors import ResourceNotFoundError


def test_uses_music_tracks_when_provided(tmp_path: Path) -> None:
    track_a = tmp_path / "track_a.mp3"
    track_b = tmp_path / "track_b.mp3"
    track_a.write_bytes(b"a")
    track_b.write_bytes(b"b")

    resolved = resolve_background_audio_paths(
        tmp_path,
        PropertyReelTemplate(),
        shuffle_candidates=False,
        music_tracks=(track_a, track_b),
    )

    assert resolved == (track_a, track_b)


def test_skips_missing_music_track_files_and_keeps_present_ones(tmp_path: Path) -> None:
    track_a = tmp_path / "track_a.mp3"
    track_a.write_bytes(b"a")
    missing = tmp_path / "missing.mp3"

    resolved = resolve_background_audio_paths(
        tmp_path,
        PropertyReelTemplate(),
        shuffle_candidates=False,
        music_tracks=(track_a, missing),
    )

    assert resolved == (track_a,)


def test_music_tracks_all_missing_raises_music_blob_missing(tmp_path: Path) -> None:
    missing = tmp_path / "missing.mp3"

    with pytest.raises(ResourceNotFoundError) as exc_info:
        resolve_background_audio_paths(
            tmp_path,
            PropertyReelTemplate(),
            shuffle_candidates=False,
            music_tracks=(missing,),
        )

    assert exc_info.value.code == "MUSIC_BLOB_MISSING"


def test_none_music_tracks_falls_back_to_legacy_scan(tmp_path: Path) -> None:
    assets_music = tmp_path / "assets" / "music"
    assets_music.mkdir(parents=True, exist_ok=True)
    fallback = assets_music / "legacy.mp3"
    fallback.write_bytes(b"legacy")

    resolved = resolve_background_audio_paths(
        tmp_path,
        PropertyReelTemplate(),
        shuffle_candidates=False,
        music_tracks=None,
    )

    assert resolved == (fallback,)


def test_empty_music_tracks_also_falls_back_to_legacy_scan(tmp_path: Path) -> None:
    assets_music = tmp_path / "assets" / "music"
    assets_music.mkdir(parents=True, exist_ok=True)
    fallback = assets_music / "legacy.mp3"
    fallback.write_bytes(b"legacy")

    resolved = resolve_background_audio_paths(
        tmp_path,
        PropertyReelTemplate(),
        shuffle_candidates=False,
        music_tracks=(),
    )

    assert resolved == (fallback,)
