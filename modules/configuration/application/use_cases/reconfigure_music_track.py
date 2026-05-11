"""Reconfigure (update) an existing music track."""

from __future__ import annotations

from dataclasses import dataclass

from modules.configuration.domain import MusicTrack
from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
    music_track_not_found_error,
)
from shared.db import DatabaseUnitOfWork


@dataclass(frozen=True, slots=True)
class ReconfigureMusicTrackInput:
    agency_id: str
    music_id: str
    display_name: str | None = None
    object_key: str | None = None
    duration_seconds: int | None = None
    is_default: bool | None = None


class ReconfigureMusicTrackUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        data: ReconfigureMusicTrackInput,
    ) -> MusicTrack:
        if uow.configuration is None:
            raise RuntimeError("The unit of work is not active.")
        normalized_agency = str(data.agency_id or "").strip()
        normalized_music = str(data.music_id or "").strip()
        ensure_agency_exists(uow, normalized_agency)

        existing = uow.configuration.music.get(music_id=normalized_music)
        if existing is None or existing.agency_id != normalized_agency:
            raise music_track_not_found_error(normalized_music)

        updated = uow.configuration.music.update(
            music_id=normalized_music,
            display_name=data.display_name,
            object_key=data.object_key,
            duration_seconds=data.duration_seconds,
            is_default=data.is_default,
        )
        if updated is None:
            raise music_track_not_found_error(normalized_music)
        return updated


__all__ = ["ReconfigureMusicTrackInput", "ReconfigureMusicTrackUseCase"]
