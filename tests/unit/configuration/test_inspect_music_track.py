"""Unit tests for InspectMusicTrackUseCase."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.configuration.application.use_cases.inspect_music_track import (
    InspectMusicTrackUseCase,
)
from shared.errors import ResourceNotFoundError
from tests.unit.configuration._uow_stubs import StubMusic, build_uow


def test_inspect_returns_track_when_owned_by_agency() -> None:
    track = SimpleNamespace(music_id="m1", agency_id="agency-1", display_name="A")
    uow = build_uow(music=StubMusic(tracks={"m1": track}))
    result = InspectMusicTrackUseCase().execute(
        uow=uow, agency_id="agency-1", music_id="m1"
    )
    assert result is track


def test_inspect_raises_when_track_belongs_to_other_agency() -> None:
    track = SimpleNamespace(music_id="m1", agency_id="other", display_name="A")
    uow = build_uow(music=StubMusic(tracks={"m1": track}))
    with pytest.raises(ResourceNotFoundError) as exc_info:
        InspectMusicTrackUseCase().execute(
            uow=uow, agency_id="agency-1", music_id="m1"
        )
    assert exc_info.value.code == "MUSIC_TRACK_NOT_FOUND"


def test_inspect_raises_when_track_does_not_exist() -> None:
    uow = build_uow(music=StubMusic(tracks={}))
    with pytest.raises(ResourceNotFoundError) as exc_info:
        InspectMusicTrackUseCase().execute(
            uow=uow, agency_id="agency-1", music_id="missing"
        )
    assert exc_info.value.code == "MUSIC_TRACK_NOT_FOUND"


def test_inspect_raises_when_agency_missing() -> None:
    uow = build_uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        InspectMusicTrackUseCase().execute(
            uow=uow, agency_id="missing", music_id="m1"
        )
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"
