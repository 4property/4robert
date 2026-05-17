"""Unit tests for :class:`UploadMusicTrackUseCase`.

The use case orchestrates blob write -> ffprobe -> register row, so we
stub the ffprobe runner and the registration use case to exercise the
control flow without shelling out to ffmpeg.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.configuration.application.use_cases.register_music_track import (
    RegisterMusicTrackUseCase,
)
from modules.configuration.application.use_cases.upload_music_track import (
    MUSIC_TRACK_MAX_DURATION_SECONDS,
    UploadMusicTrackInput,
    UploadMusicTrackUseCase,
)
from shared.errors import ApplicationError, PipelineError, ValidationError
from tests.unit.configuration._uow_stubs import StubMusic, build_uow


def test_upload_writes_blob_and_registers_row(tmp_path: Path) -> None:
    music = StubMusic()
    uow = build_uow(music=music)
    use_case = UploadMusicTrackUseCase(
        workspace_dir=tmp_path,
        ffprobe_runner=lambda _path: 42,
    )

    track = use_case.execute(
        uow=uow,
        data=UploadMusicTrackInput(
            agency_id="agency-1",
            filename="sunset.mp3",
            body=b"FAKE-AUDIO-BYTES",
            display_name="Sunset Drive",
            is_default=True,
        ),
    )

    assert track.display_name == "Sunset Drive"
    assert track.duration_seconds == 42
    assert track.is_default is True
    assert music.add_calls[0]["agency_id"] == "agency-1"
    assert music.add_calls[0]["object_key"].endswith("/music/sunset.mp3")

    # Blob written under the agency-music folder.
    safe_agency = "agency-1"
    persisted_dir = (
        tmp_path
        / "generated_media"
        / "_agency_music"
        / safe_agency
    )
    files_on_disk = list(persisted_dir.iterdir())
    assert len(files_on_disk) == 1
    assert files_on_disk[0].read_bytes() == b"FAKE-AUDIO-BYTES"


def test_upload_cleans_blob_when_ffprobe_fails(tmp_path: Path) -> None:
    music = StubMusic()
    uow = build_uow(music=music)

    def _failing_runner(_path: Path) -> int:
        from modules.configuration.application.use_cases.upload_music_track import (
            _FfprobeFailedError,
        )

        raise _FfprobeFailedError("ffprobe exited with status 1")

    use_case = UploadMusicTrackUseCase(
        workspace_dir=tmp_path,
        ffprobe_runner=_failing_runner,
    )
    with pytest.raises(ValidationError) as exc_info:
        use_case.execute(
            uow=uow,
            data=UploadMusicTrackInput(
                agency_id="agency-1",
                filename="bad.mp3",
                body=b"garbage",
                display_name="Bad Track",
            ),
        )
    assert exc_info.value.code == "MUSIC_TRACK_AUDIO_INVALID"
    assert music.add_calls == []

    # Blob must have been cleaned up.
    persisted_dir = (
        tmp_path / "generated_media" / "_agency_music" / "agency-1"
    )
    if persisted_dir.exists():
        assert list(persisted_dir.iterdir()) == []


def test_upload_rejects_duration_over_limit(tmp_path: Path) -> None:
    music = StubMusic()
    uow = build_uow(music=music)
    use_case = UploadMusicTrackUseCase(
        workspace_dir=tmp_path,
        ffprobe_runner=lambda _path: MUSIC_TRACK_MAX_DURATION_SECONDS + 1,
    )
    with pytest.raises(ValidationError) as exc_info:
        use_case.execute(
            uow=uow,
            data=UploadMusicTrackInput(
                agency_id="agency-1",
                filename="too-long.mp3",
                body=b"FAKE",
                display_name="Too Long",
            ),
        )
    assert exc_info.value.code == "MUSIC_TRACK_AUDIO_INVALID"
    assert music.add_calls == []
    persisted_dir = (
        tmp_path / "generated_media" / "_agency_music" / "agency-1"
    )
    if persisted_dir.exists():
        assert list(persisted_dir.iterdir()) == []


def test_upload_cleans_blob_when_persistence_fails(tmp_path: Path) -> None:
    music = StubMusic()
    uow = build_uow(music=music)

    class _FailingRegister(RegisterMusicTrackUseCase):
        def execute(self, *, uow, data):  # type: ignore[override]
            raise PipelineError(
                "boom",
                stage="music_track_persist",
                code="MUSIC_TRACK_SAVE_FAILED",
            )

    use_case = UploadMusicTrackUseCase(
        workspace_dir=tmp_path,
        register_music_track=_FailingRegister(),
        ffprobe_runner=lambda _path: 30,
    )
    with pytest.raises(ApplicationError) as exc_info:
        use_case.execute(
            uow=uow,
            data=UploadMusicTrackInput(
                agency_id="agency-1",
                filename="crash.mp3",
                body=b"FAKE",
                display_name="Crash",
            ),
        )
    assert exc_info.value.code == "MUSIC_TRACK_SAVE_FAILED"
    persisted_dir = (
        tmp_path / "generated_media" / "_agency_music" / "agency-1"
    )
    if persisted_dir.exists():
        assert list(persisted_dir.iterdir()) == []


def test_upload_zero_duration_is_rejected(tmp_path: Path) -> None:
    music = StubMusic()
    uow = build_uow(music=music)
    use_case = UploadMusicTrackUseCase(
        workspace_dir=tmp_path,
        ffprobe_runner=lambda _path: 0,
    )
    with pytest.raises(ValidationError) as exc_info:
        use_case.execute(
            uow=uow,
            data=UploadMusicTrackInput(
                agency_id="agency-1",
                filename="empty.mp3",
                body=b"FAKE",
                display_name="Empty",
            ),
        )
    assert exc_info.value.code == "MUSIC_TRACK_AUDIO_INVALID"
    assert music.add_calls == []
