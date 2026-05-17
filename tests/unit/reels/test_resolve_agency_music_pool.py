"""Unit tests for the per-agency music pool selection (Features 23 + 24).

The selection rules:

* default tracks (``is_default=True``) take precedence regardless of
  the flag;
* otherwise the behaviour depends on the persisted
  ``settings.music.selection_rules.fallback_to_full_library`` flag
  (Feature 24): ``True`` falls back to the full library so an agency
  that toggled every default off still renders, ``False`` raises
  ``PropertyReelError`` with ``code="MUSIC_NO_DEFAULT_TRACKS"`` so the
  reel fails loudly;
* an empty library raises ``PropertyReelError`` with
  ``code="MUSIC_NO_TRACKS"`` (regardless of the flag) so the reel job
  surfaces a clear error instead of silently producing a silent reel.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.configuration.domain import MusicTrack
from modules.reels.application.use_cases._resolve_agency_music_pool import (
    resolve_agency_background_audio_candidates,
)
from shared.errors import PropertyReelError


def _build_track(
    *,
    music_id: str,
    object_key: str,
    is_default: bool,
) -> MusicTrack:
    return MusicTrack(
        music_id=music_id,
        agency_id="agency-1",
        display_name=music_id,
        object_key=object_key,
        duration_seconds=42,
        is_default=is_default,
        created_at="2026-05-14T00:00:00Z",
    )


def _stub_uow(tracks: tuple[MusicTrack, ...]) -> SimpleNamespace:
    class _Music:
        def list_for_agency(self, agency_id: str) -> tuple[MusicTrack, ...]:  # noqa: ARG002
            return tracks

    return SimpleNamespace(configuration=SimpleNamespace(music=_Music()))


def _write_blob(tmp_path: Path, agency_id: str, filename: str) -> Path:
    music_dir = tmp_path / "generated_media" / "_agency_music" / agency_id
    music_dir.mkdir(parents=True, exist_ok=True)
    blob = music_dir / filename
    blob.write_bytes(b"mp3")
    return blob


def test_returns_default_tracks_when_present(tmp_path: Path) -> None:
    default_blob = _write_blob(tmp_path, "agency-1", "default.mp3")
    _write_blob(tmp_path, "agency-1", "library.mp3")
    uow = _stub_uow(
        (
            _build_track(
                music_id="default",
                object_key="agencies/agency-1/music/default.mp3",
                is_default=True,
            ),
            _build_track(
                music_id="library",
                object_key="agencies/agency-1/music/library.mp3",
                is_default=False,
            ),
        )
    )

    resolved = resolve_agency_background_audio_candidates(
        uow=uow, agency_id="agency-1", workspace_dir=tmp_path
    )

    assert resolved == (default_blob,)


def test_falls_back_to_library_when_no_defaults(tmp_path: Path) -> None:
    library_blob = _write_blob(tmp_path, "agency-1", "library.mp3")
    uow = _stub_uow(
        (
            _build_track(
                music_id="library",
                object_key="agencies/agency-1/music/library.mp3",
                is_default=False,
            ),
        )
    )

    resolved = resolve_agency_background_audio_candidates(
        uow=uow, agency_id="agency-1", workspace_dir=tmp_path
    )

    assert resolved == (library_blob,)


def test_empty_library_raises_music_no_tracks(tmp_path: Path) -> None:
    uow = _stub_uow(())

    with pytest.raises(PropertyReelError) as exc_info:
        resolve_agency_background_audio_candidates(
            uow=uow, agency_id="agency-1", workspace_dir=tmp_path
        )

    assert exc_info.value.code == "MUSIC_NO_TRACKS"


def test_missing_configuration_namespace_returns_empty(tmp_path: Path) -> None:
    uow = SimpleNamespace()

    assert (
        resolve_agency_background_audio_candidates(
            uow=uow, agency_id="agency-1", workspace_dir=tmp_path
        )
        == ()
    )


def test_default_tracks_win_even_when_fallback_disabled(tmp_path: Path) -> None:
    """Feature 24: when at least one default exists the flag is ignored.

    The flag only branches the "no default tracks" path; here the
    default pool is non-empty so the resolver must use it regardless of
    ``fallback_to_full_library``.
    """
    default_blob = _write_blob(tmp_path, "agency-1", "default.mp3")
    _write_blob(tmp_path, "agency-1", "library.mp3")
    uow = _stub_uow(
        (
            _build_track(
                music_id="default",
                object_key="agencies/agency-1/music/default.mp3",
                is_default=True,
            ),
            _build_track(
                music_id="library",
                object_key="agencies/agency-1/music/library.mp3",
                is_default=False,
            ),
        )
    )

    resolved = resolve_agency_background_audio_candidates(
        uow=uow,
        agency_id="agency-1",
        workspace_dir=tmp_path,
        fallback_to_full_library=False,
    )

    assert resolved == (default_blob,)


def test_no_defaults_with_fallback_false_raises_music_no_default_tracks(
    tmp_path: Path,
) -> None:
    """Feature 24: empty default pool + flag=false → MUSIC_NO_DEFAULT_TRACKS.

    The library has tracks but none are marked default. With the
    fallback disabled the renderer must surface a clear failure rather
    than silently pick a non-default track.
    """
    _write_blob(tmp_path, "agency-1", "library.mp3")
    uow = _stub_uow(
        (
            _build_track(
                music_id="library",
                object_key="agencies/agency-1/music/library.mp3",
                is_default=False,
            ),
        )
    )

    with pytest.raises(PropertyReelError) as exc_info:
        resolve_agency_background_audio_candidates(
            uow=uow,
            agency_id="agency-1",
            workspace_dir=tmp_path,
            fallback_to_full_library=False,
        )

    assert exc_info.value.code == "MUSIC_NO_DEFAULT_TRACKS"


def test_no_defaults_with_fallback_true_uses_library(tmp_path: Path) -> None:
    """Feature 24: default ``True`` keeps the pre-feature-24 behaviour."""
    library_blob = _write_blob(tmp_path, "agency-1", "library.mp3")
    uow = _stub_uow(
        (
            _build_track(
                music_id="library",
                object_key="agencies/agency-1/music/library.mp3",
                is_default=False,
            ),
        )
    )

    resolved = resolve_agency_background_audio_candidates(
        uow=uow,
        agency_id="agency-1",
        workspace_dir=tmp_path,
        fallback_to_full_library=True,
    )

    assert resolved == (library_blob,)


def test_blob_missing_propagates_as_music_blob_missing(tmp_path: Path) -> None:
    # The default track row points at a blob that does not exist on disk.
    uow = _stub_uow(
        (
            _build_track(
                music_id="default",
                object_key="agencies/agency-1/music/missing.mp3",
                is_default=True,
            ),
        )
    )

    from shared.errors import ResourceNotFoundError

    with pytest.raises(ResourceNotFoundError) as exc_info:
        resolve_agency_background_audio_candidates(
            uow=uow, agency_id="agency-1", workspace_dir=tmp_path
        )

    assert exc_info.value.code == "MUSIC_BLOB_MISSING"
