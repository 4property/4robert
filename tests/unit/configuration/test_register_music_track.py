"""Unit tests for RegisterMusicTrackUseCase."""

from __future__ import annotations

import pytest

from modules.configuration.application.use_cases.register_music_track import (
    RegisterMusicTrackInput,
    RegisterMusicTrackUseCase,
)
from shared.errors import ResourceNotFoundError, ValidationError
from tests.unit.configuration._uow_stubs import StubMusic, build_uow


def test_register_creates_track_and_assigns_id() -> None:
    repo = StubMusic()
    uow = build_uow(music=repo)
    track = RegisterMusicTrackUseCase().execute(
        uow=uow,
        data=RegisterMusicTrackInput(
            agency_id="agency-1",
            display_name="Sunset Drive",
            object_key="agencies/ckp/sunset.mp3",
            duration_seconds=28,
        ),
    )
    assert track.display_name == "Sunset Drive"
    assert repo.add_calls[0]["agency_id"] == "agency-1"
    assert repo.add_calls[0]["display_name"] == "Sunset Drive"
    assert isinstance(repo.add_calls[0]["music_id"], str)
    assert repo.add_calls[0]["music_id"]


def test_register_rejects_blank_display_name() -> None:
    uow = build_uow()
    with pytest.raises(ValidationError) as exc_info:
        RegisterMusicTrackUseCase().execute(
            uow=uow,
            data=RegisterMusicTrackInput(
                agency_id="agency-1",
                display_name="   ",
                object_key="x",
                duration_seconds=10,
            ),
        )
    assert exc_info.value.code == "MUSIC_TRACK_DISPLAY_NAME_REQUIRED"


def test_register_rejects_zero_duration() -> None:
    uow = build_uow()
    with pytest.raises(ValidationError) as exc_info:
        RegisterMusicTrackUseCase().execute(
            uow=uow,
            data=RegisterMusicTrackInput(
                agency_id="agency-1",
                display_name="Track",
                object_key="x",
                duration_seconds=0,
            ),
        )
    assert exc_info.value.code == "MUSIC_TRACK_INVALID_DURATION"


def test_register_raises_when_agency_missing() -> None:
    uow = build_uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        RegisterMusicTrackUseCase().execute(
            uow=uow,
            data=RegisterMusicTrackInput(
                agency_id="missing",
                display_name="Track",
                object_key="x",
                duration_seconds=10,
            ),
        )
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"
