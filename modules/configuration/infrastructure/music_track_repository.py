from __future__ import annotations

from sqlalchemy import text

from modules.configuration.domain import MusicTrack
from modules.configuration.infrastructure.repository_helpers import isoformat
from shared.db.repository_base import ModuleRepository, utcnow


class MusicTracksRepository(ModuleRepository):
    def list_for_agency(self, agency_id: str) -> tuple[MusicTrack, ...]:
        rows = self.session.execute(
            text(
                "SELECT id, agency_id, display_name, object_key, duration_seconds, "
                "is_default, created_at FROM agency_music_tracks "
                "WHERE agency_id = :agency_id ORDER BY display_name ASC"
            ),
            {"agency_id": agency_id},
        ).all()
        return tuple(
            MusicTrack(
                music_id=str(row.id),
                agency_id=str(row.agency_id),
                display_name=str(row.display_name or ""),
                object_key=str(row.object_key or ""),
                duration_seconds=int(row.duration_seconds or 0),
                is_default=bool(row.is_default),
                created_at=isoformat(row.created_at) or "",
            )
            for row in rows
        )

    def get(self, *, music_id: str) -> MusicTrack | None:
        row = self.session.execute(
            text(
                "SELECT id, agency_id, display_name, object_key, duration_seconds, "
                "is_default, created_at FROM agency_music_tracks WHERE id = :music_id"
            ),
            {"music_id": music_id},
        ).first()
        if row is None:
            return None
        return MusicTrack(
            music_id=str(row.id),
            agency_id=str(row.agency_id),
            display_name=str(row.display_name or ""),
            object_key=str(row.object_key or ""),
            duration_seconds=int(row.duration_seconds or 0),
            is_default=bool(row.is_default),
            created_at=isoformat(row.created_at) or "",
        )

    def add_track(
        self,
        *,
        music_id: str,
        agency_id: str,
        display_name: str,
        object_key: str,
        duration_seconds: int,
        is_default: bool = False,
    ) -> MusicTrack:
        timestamp = utcnow()
        self.session.execute(
            text(
                "INSERT INTO agency_music_tracks ("
                "id, agency_id, display_name, object_key, duration_seconds, "
                "is_default, created_at"
                ") VALUES ("
                ":id, :agency_id, :display_name, :object_key, :duration_seconds, "
                ":is_default, :created_at"
                ")"
            ),
            {
                "id": music_id,
                "agency_id": agency_id,
                "display_name": display_name,
                "object_key": object_key,
                "duration_seconds": duration_seconds,
                "is_default": is_default,
                "created_at": timestamp,
            },
        )
        return MusicTrack(
            music_id=music_id,
            agency_id=agency_id,
            display_name=display_name,
            object_key=object_key,
            duration_seconds=duration_seconds,
            is_default=is_default,
            created_at=timestamp.isoformat(),
        )

    def update(
        self,
        *,
        music_id: str,
        display_name: str | None = None,
        object_key: str | None = None,
        duration_seconds: int | None = None,
        is_default: bool | None = None,
    ) -> MusicTrack | None:
        existing = self.get(music_id=music_id)
        if existing is None:
            return None
        merged = {
            "display_name": display_name if display_name is not None else existing.display_name,
            "object_key": object_key if object_key is not None else existing.object_key,
            "duration_seconds": int(
                duration_seconds if duration_seconds is not None else existing.duration_seconds
            ),
            "is_default": bool(
                is_default if is_default is not None else existing.is_default
            ),
        }
        self.session.execute(
            text(
                "UPDATE agency_music_tracks SET "
                "display_name = :display_name, "
                "object_key = :object_key, "
                "duration_seconds = :duration_seconds, "
                "is_default = :is_default "
                "WHERE id = :music_id"
            ),
            {"music_id": music_id, **merged},
        )
        return self.get(music_id=music_id)

    def delete(self, *, music_id: str) -> bool:
        row = self.session.execute(
            text("DELETE FROM agency_music_tracks WHERE id = :music_id RETURNING id"),
            {"music_id": music_id},
        ).first()
        return row is not None


__all__ = ["MusicTracksRepository"]
