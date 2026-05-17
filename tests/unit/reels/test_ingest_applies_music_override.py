"""Unit tests for feature 25 — music override swap during ingest.

The worker's render+publish loop assembles a ``PropertyContext`` by
running :class:`IngestPropertyIntoReelUseCase` first. When the job
carries ``override_music_track_id`` on its ``SocialPublishContext``,
the ingest must replace the resolved agency music pool with a
single-element tuple pointing to the override track. If the track
no longer resolves (deleted between PATCH and render — the column
already flipped to NULL but the in-flight job still carries the old
id), the helper falls back to the resolved pool instead of failing
the render.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from modules.configuration.domain import MusicTrack
from modules.reels.application.use_cases.ingest_property_into_reel import (
    IngestPropertyIntoReelUseCase,
)
from modules.reels.domain.types import SocialPublishContext


class _StubMusicRepo:
    def __init__(self, *, tracks: dict[str, MusicTrack] | None = None) -> None:
        self.tracks = dict(tracks or {})
        self.calls: list[str] = []

    def get(self, *, music_id: str) -> MusicTrack | None:
        self.calls.append(str(music_id or ""))
        return self.tracks.get(music_id)


def _build_uow(*, music_repo: _StubMusicRepo) -> Any:
    return SimpleNamespace(
        configuration=SimpleNamespace(music=music_repo),
    )


def _make_use_case(tmp_path: Path) -> IngestPropertyIntoReelUseCase:
    return IngestPropertyIntoReelUseCase(
        workspace_dir=tmp_path,
        property_url_template="https://example.com/{slug}",
        property_url_tracking_params=None,
        social_publishing_enabled=True,
    )


def _make_track(*, music_id: str, agency_id: str, object_key: str) -> MusicTrack:
    return MusicTrack(
        music_id=music_id,
        agency_id=agency_id,
        display_name="Override Track",
        object_key=object_key,
        duration_seconds=30,
        is_default=False,
        created_at="",
    )


def _seed_track_on_disk(workspace_dir: Path, *, agency_id: str, filename: str) -> Path:
    music_dir = (
        workspace_dir / "generated_media" / "_agency_music" / agency_id
    )
    music_dir.mkdir(parents=True, exist_ok=True)
    blob_path = music_dir / filename
    blob_path.write_bytes(b"stub-music-track")
    return blob_path


def test_apply_music_track_override_swaps_pool_for_single_track(tmp_path: Path) -> None:
    """Resolved pool tuple is replaced by the override track tuple."""
    music_id = "override-1"
    agency_id = "agency-1"
    filename = "override.mp3"
    blob_path = _seed_track_on_disk(
        tmp_path, agency_id=agency_id, filename=filename
    )
    object_key = f"agencies/{agency_id}/music/{filename}"
    track = _make_track(
        music_id=music_id, agency_id=agency_id, object_key=object_key
    )
    uow = _build_uow(music_repo=_StubMusicRepo(tracks={music_id: track}))
    use_case = _make_use_case(tmp_path)
    publish_context = SocialPublishContext(
        provider="gohighlevel",
        location_id="loc-1",
        access_token="tok",
        platforms=("instagram",),
        override_music_track_id=music_id,
    )

    fallback_pool = (Path("/tmp/pool-track-a.mp3"), Path("/tmp/pool-track-b.mp3"))
    swapped = use_case._apply_music_track_override(
        uow=uow,
        agency_id=agency_id,
        publish_context=publish_context,
        background_audio_candidates=fallback_pool,
    )
    assert swapped == (blob_path,)


def test_apply_music_track_override_falls_back_when_track_missing(
    tmp_path: Path,
) -> None:
    """Track id present in the job but missing in the DB → fallback to pool."""
    uow = _build_uow(music_repo=_StubMusicRepo(tracks={}))
    use_case = _make_use_case(tmp_path)
    publish_context = SocialPublishContext(
        provider="gohighlevel",
        location_id="loc-1",
        access_token="tok",
        platforms=("instagram",),
        override_music_track_id="never-existed",
    )
    fallback_pool = (Path("/tmp/pool-track-a.mp3"),)
    result = use_case._apply_music_track_override(
        uow=uow,
        agency_id="agency-1",
        publish_context=publish_context,
        background_audio_candidates=fallback_pool,
    )
    assert result == fallback_pool


def test_apply_music_track_override_falls_back_when_cross_agency(
    tmp_path: Path,
) -> None:
    """Track that exists but belongs to another tenant → fallback to pool."""
    music_id = "owned-by-someone-else"
    foreign_track = _make_track(
        music_id=music_id,
        agency_id="other-tenant",
        object_key="agencies/other-tenant/music/x.mp3",
    )
    uow = _build_uow(music_repo=_StubMusicRepo(tracks={music_id: foreign_track}))
    use_case = _make_use_case(tmp_path)
    publish_context = SocialPublishContext(
        provider="gohighlevel",
        location_id="loc-1",
        access_token="tok",
        platforms=("instagram",),
        override_music_track_id=music_id,
    )
    fallback_pool = (Path("/tmp/pool-track-a.mp3"),)
    result = use_case._apply_music_track_override(
        uow=uow,
        agency_id="agency-1",
        publish_context=publish_context,
        background_audio_candidates=fallback_pool,
    )
    assert result == fallback_pool


def test_apply_music_track_override_noop_without_override(tmp_path: Path) -> None:
    """No ``override_music_track_id`` on the context → pass-through."""
    uow = _build_uow(music_repo=_StubMusicRepo())
    use_case = _make_use_case(tmp_path)
    publish_context = SocialPublishContext(
        provider="gohighlevel",
        location_id="loc-1",
        access_token="tok",
        platforms=("instagram",),
    )
    fallback_pool = (Path("/tmp/pool-track-a.mp3"),)
    result = use_case._apply_music_track_override(
        uow=uow,
        agency_id="agency-1",
        publish_context=publish_context,
        background_audio_candidates=fallback_pool,
    )
    assert result == fallback_pool


def test_apply_music_track_override_noop_without_publish_context(
    tmp_path: Path,
) -> None:
    """``publish_context=None`` (legacy / publishing disabled) → pass-through."""
    uow = _build_uow(music_repo=_StubMusicRepo())
    use_case = _make_use_case(tmp_path)
    fallback_pool = (Path("/tmp/pool-track-a.mp3"),)
    result = use_case._apply_music_track_override(
        uow=uow,
        agency_id="agency-1",
        publish_context=None,
        background_audio_candidates=fallback_pool,
    )
    assert result == fallback_pool


def test_apply_music_track_override_handles_unit_test_uow_without_music_repo(
    tmp_path: Path,
) -> None:
    """A UoW without ``configuration.music`` → pass-through (test ergonomics)."""
    uow_without_music = SimpleNamespace(configuration=SimpleNamespace(music=None))
    use_case = _make_use_case(tmp_path)
    publish_context = SocialPublishContext(
        provider="gohighlevel",
        location_id="loc-1",
        access_token="tok",
        platforms=("instagram",),
        override_music_track_id="x",
    )
    fallback_pool = (Path("/tmp/pool-track-a.mp3"),)
    result = use_case._apply_music_track_override(
        uow=uow_without_music,
        agency_id="agency-1",
        publish_context=publish_context,
        background_audio_candidates=fallback_pool,
    )
    assert result == fallback_pool
