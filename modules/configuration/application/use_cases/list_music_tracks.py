"""List the music tracks attached to an agency."""

from __future__ import annotations

from modules.configuration.domain import MusicTrack
from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
)
from shared.db import DatabaseUnitOfWork


class ListMusicTracksUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
    ) -> tuple[MusicTrack, ...]:
        if uow.configuration is None:
            raise RuntimeError("The unit of work is not active.")
        ensure_agency_exists(uow, agency_id)
        return uow.configuration.music.list_for_agency(
            str(agency_id or "").strip()
        )


__all__ = ["ListMusicTracksUseCase"]
