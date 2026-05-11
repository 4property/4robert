"""Unit tests for ReconfigureMusicTrackUseCase."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.configuration.application.use_cases.reconfigure_music_track import (
    ReconfigureMusicTrackInput,
    ReconfigureMusicTrackUseCase,
)
from shared.errors import ResourceNotFoundError
from tests.unit.configuration._uow_stubs import StubMusic, build_uow


def test_reconfigure_updates_existing_track() -> None:
    track = SimpleNamespace(
        music_id="m1",
        agency_id="agency-1",
        display_name="Old",
        object_key="old.mp3",
        duration_seconds=10,
        is_default=False,
        created_at="now",
    )
    repo = StubMusic(tracks={"m1": track})
    uow = build_uow(music=repo)
    updated = ReconfigureMusicTrackUseCase().execute(
        uow=uow,
        data=ReconfigureMusicTrackInput(
            agency_id="agency-1",
            music_id="m1",
            display_name="New",
            duration_seconds=20,
        ),
    )
    assert updated.display_name == "New"
    assert updated.duration_seconds == 20
    assert updated.object_key == "old.mp3"  # preserved


def test_reconfigure_raises_when_track_belongs_to_other_agency() -> None:
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
        ReconfigureMusicTrackUseCase().execute(
            uow=uow,
            data=ReconfigureMusicTrackInput(
                agency_id="agency-1", music_id="m1", display_name="y"
            ),
        )
    assert exc_info.value.code == "MUSIC_TRACK_NOT_FOUND"


def test_reconfigure_raises_when_track_does_not_exist() -> None:
    uow = build_uow(music=StubMusic(tracks={}))
    with pytest.raises(ResourceNotFoundError) as exc_info:
        ReconfigureMusicTrackUseCase().execute(
            uow=uow,
            data=ReconfigureMusicTrackInput(
                agency_id="agency-1", music_id="missing", display_name="x"
            ),
        )
    assert exc_info.value.code == "MUSIC_TRACK_NOT_FOUND"


def test_reconfigure_raises_when_agency_missing() -> None:
    uow = build_uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        ReconfigureMusicTrackUseCase().execute(
            uow=uow,
            data=ReconfigureMusicTrackInput(
                agency_id="missing", music_id="m1", display_name="x"
            ),
        )
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"
