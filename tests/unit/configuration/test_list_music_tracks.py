"""Unit tests for ListMusicTracksUseCase."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.configuration.application.use_cases.list_music_tracks import (
    ListMusicTracksUseCase,
)
from shared.errors import ResourceNotFoundError
from tests.unit.configuration._uow_stubs import StubMusic, build_uow


def test_list_returns_only_agency_tracks() -> None:
    track_a = SimpleNamespace(music_id="m1", agency_id="agency-1", display_name="A")
    track_b = SimpleNamespace(music_id="m2", agency_id="agency-2", display_name="B")
    repo = StubMusic(tracks={"m1": track_a, "m2": track_b})
    uow = build_uow(music=repo)
    result = ListMusicTracksUseCase().execute(uow=uow, agency_id="agency-1")
    assert result == (track_a,)


def test_list_returns_empty_tuple_when_no_tracks() -> None:
    uow = build_uow(music=StubMusic(tracks={}))
    assert ListMusicTracksUseCase().execute(uow=uow, agency_id="agency-1") == ()


def test_list_raises_when_agency_missing() -> None:
    uow = build_uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        ListMusicTracksUseCase().execute(uow=uow, agency_id="missing")
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"
