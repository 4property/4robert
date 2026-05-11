"""Decommission (delete) a music track from an agency's library."""

from __future__ import annotations

from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
    music_track_not_found_error,
)
from shared.db import DatabaseUnitOfWork


class DecommissionMusicTrackUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
        music_id: str,
    ) -> None:
        if uow.configuration is None:
            raise RuntimeError("The unit of work is not active.")
        normalized_agency = str(agency_id or "").strip()
        normalized_music = str(music_id or "").strip()
        ensure_agency_exists(uow, normalized_agency)

        existing = uow.configuration.music.get(music_id=normalized_music)
        if existing is None or existing.agency_id != normalized_agency:
            raise music_track_not_found_error(normalized_music)

        deleted = uow.configuration.music.delete(music_id=normalized_music)
        if not deleted:
            raise music_track_not_found_error(normalized_music)


__all__ = ["DecommissionMusicTrackUseCase"]
