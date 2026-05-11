"""Inspect a single music track for an agency."""

from __future__ import annotations

from modules.configuration.domain import MusicTrack
from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
    music_track_not_found_error,
)
from shared.db import DatabaseUnitOfWork


class InspectMusicTrackUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
        music_id: str,
    ) -> MusicTrack:
        if uow.configuration is None:
            raise RuntimeError("The unit of work is not active.")
        normalized_agency = str(agency_id or "").strip()
        normalized_music = str(music_id or "").strip()
        ensure_agency_exists(uow, normalized_agency)

        track = uow.configuration.music.get(music_id=normalized_music)
        if track is None or track.agency_id != normalized_agency:
            raise music_track_not_found_error(normalized_music)
        return track


__all__ = ["InspectMusicTrackUseCase"]
