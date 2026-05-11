"""Unit tests for DecommissionMusicTrackUseCase."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.configuration.application.use_cases.decommission_music_track import (
    DecommissionMusicTrackUseCase,
)
from shared.errors import ResourceNotFoundError
from tests.unit.configuration._uow_stubs import StubMusic, build_uow


def test_decommission_deletes_track() -> None:
    track = SimpleNamespace(
        music_id="m1",
        agency_id="agency-1",
        display_name="x",
        object_key="x",
        duration_seconds=1,
        is_default=False,
        created_at="",
    )
    repo = StubMusic(tracks={"m1": track})
    uow = build_uow(music=repo)
    DecommissionMusicTrackUseCase().execute(
        uow=uow, agency_id="agency-1", music_id="m1"
    )
    assert repo.delete_calls == ["m1"]


def test_decommission_raises_when_track_belongs_to_other_agency() -> None:
    track = SimpleNamespace(
        music_id="m1",
        agency_id="other",
        display_name="x",
        object_key="x",
        duration_seconds=1,
        is_default=False,
        created_at="",
    )
    uow = build_uow(music=StubMusic(tracks={"m1": track}))
    with pytest.raises(ResourceNotFoundError) as exc_info:
        DecommissionMusicTrackUseCase().execute(
            uow=uow, agency_id="agency-1", music_id="m1"
        )
    assert exc_info.value.code == "MUSIC_TRACK_NOT_FOUND"


def test_decommission_raises_when_track_does_not_exist() -> None:
    uow = build_uow(music=StubMusic(tracks={}))
    with pytest.raises(ResourceNotFoundError) as exc_info:
        DecommissionMusicTrackUseCase().execute(
            uow=uow, agency_id="agency-1", music_id="missing"
        )
    assert exc_info.value.code == "MUSIC_TRACK_NOT_FOUND"


def test_decommission_raises_when_agency_missing() -> None:
    uow = build_uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        DecommissionMusicTrackUseCase().execute(
            uow=uow, agency_id="missing", music_id="m1"
        )
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"
