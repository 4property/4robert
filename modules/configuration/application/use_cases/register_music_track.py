"""Register a new music track for an agency."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from modules.configuration.domain import MusicTrack
from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
)
from shared.db import DatabaseUnitOfWork
from shared.errors import ValidationError


@dataclass(frozen=True, slots=True)
class RegisterMusicTrackInput:
    agency_id: str
    display_name: str
    object_key: str
    duration_seconds: int
    is_default: bool = False


class RegisterMusicTrackUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        data: RegisterMusicTrackInput,
    ) -> MusicTrack:
        if uow.configuration is None:
            raise RuntimeError("The unit of work is not active.")
        agency_id = str(data.agency_id or "").strip()
        display_name = str(data.display_name or "").strip()
        object_key = str(data.object_key or "").strip()

        if not display_name:
            raise ValidationError(
                "A music track display name is required.",
                code="MUSIC_TRACK_DISPLAY_NAME_REQUIRED",
                context={"agency_id": agency_id},
            )
        if not object_key:
            raise ValidationError(
                "A music track object key is required.",
                code="MUSIC_TRACK_OBJECT_KEY_REQUIRED",
                context={"agency_id": agency_id},
            )
        if int(data.duration_seconds or 0) <= 0:
            raise ValidationError(
                "Music track duration must be a positive integer.",
                code="MUSIC_TRACK_INVALID_DURATION",
                context={
                    "agency_id": agency_id,
                    "duration_seconds": data.duration_seconds,
                },
            )

        ensure_agency_exists(uow, agency_id)

        return uow.configuration.music.add_track(
            music_id=str(uuid4()),
            agency_id=agency_id,
            display_name=display_name,
            object_key=object_key,
            duration_seconds=int(data.duration_seconds),
            is_default=bool(data.is_default),
        )


__all__ = ["RegisterMusicTrackInput", "RegisterMusicTrackUseCase"]
