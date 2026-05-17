from __future__ import annotations

from typing import Any, Iterable, Mapping

from sqlalchemy import text

from modules.configuration.domain import ReelDefaults
from modules.configuration.infrastructure.repository_helpers import (
    isoformat,
    jsonb_to_mapping,
    list_param,
    mapping_to_jsonb,
)
from shared.db.repository_base import ModuleRepository, utcnow


class ReelDefaultsRepository(ModuleRepository):
    def get(self, agency_id: str) -> ReelDefaults | None:
        row = self.session.execute(
            text(
                "SELECT agency_id, platforms, duration_seconds, music_id, "
                "intro_enabled, caption_template, render_template_id, settings, "
                "outro_enabled, created_at, updated_at "
                "FROM agency_reel_defaults WHERE agency_id = :agency_id"
            ),
            {"agency_id": agency_id},
        ).first()
        if row is None:
            return None
        return ReelDefaults(
            agency_id=str(row.agency_id),
            platforms=tuple(row.platforms or ()),
            duration_seconds=int(row.duration_seconds or 0),
            music_id=str(row.music_id or ""),
            intro_enabled=bool(row.intro_enabled),
            caption_template=str(row.caption_template or ""),
            render_template_id=str(row.render_template_id or "classic"),
            settings=jsonb_to_mapping(row.settings),
            outro_enabled=bool(row.outro_enabled),
            created_at=isoformat(row.created_at) or "",
            updated_at=isoformat(row.updated_at) or "",
        )

    def upsert(
        self,
        *,
        agency_id: str,
        platforms: Iterable[str] | None = None,
        duration_seconds: int | None = None,
        music_id: str | None = None,
        intro_enabled: bool | None = None,
        caption_template: str | None = None,
        render_template_id: str | None = None,
        settings: Mapping[str, Any] | None = None,
        outro_enabled: bool | None = None,
    ) -> ReelDefaults:
        existing = self.get(agency_id)
        timestamp = utcnow()
        merged_platforms = (
            list_param(platforms)
            if platforms is not None
            else (
                list(existing.platforms)
                if existing
                else [
                    "tiktok",
                    "instagram",
                    "linkedin",
                    "youtube",
                    "facebook",
                    "gbp",
                    "pinterest",
                ]
            )
        )
        merged = {
            "platforms": merged_platforms,
            "duration_seconds": int(
                duration_seconds
                if duration_seconds is not None
                else (existing.duration_seconds if existing else 30)
            ),
            "music_id": music_id
            if music_id is not None
            else (existing.music_id if existing else ""),
            "intro_enabled": bool(
                intro_enabled
                if intro_enabled is not None
                else (existing.intro_enabled if existing else True)
            ),
            "caption_template": caption_template
            if caption_template is not None
            else (existing.caption_template if existing else ""),
            "render_template_id": (
                str(render_template_id or "").strip()
                if render_template_id is not None
                else (existing.render_template_id if existing else "classic")
            )
            or "classic",
            "settings": mapping_to_jsonb(
                settings
                if settings is not None
                else (existing.settings if existing else {})
            ),
            "outro_enabled": bool(
                outro_enabled
                if outro_enabled is not None
                else (existing.outro_enabled if existing else False)
            ),
        }
        self.session.execute(
            text(
                "INSERT INTO agency_reel_defaults ("
                "agency_id, platforms, duration_seconds, music_id, intro_enabled, "
                "caption_template, render_template_id, settings, outro_enabled, "
                "created_at, updated_at"
                ") VALUES ("
                ":agency_id, :platforms, :duration_seconds, :music_id, "
                ":intro_enabled, :caption_template, :render_template_id, "
                "CAST(:settings AS jsonb), :outro_enabled, :created_at, :updated_at"
                ") ON CONFLICT (agency_id) DO UPDATE SET "
                "platforms = EXCLUDED.platforms, "
                "duration_seconds = EXCLUDED.duration_seconds, "
                "music_id = EXCLUDED.music_id, "
                "intro_enabled = EXCLUDED.intro_enabled, "
                "caption_template = EXCLUDED.caption_template, "
                "render_template_id = EXCLUDED.render_template_id, "
                "settings = EXCLUDED.settings, "
                "outro_enabled = EXCLUDED.outro_enabled, "
                "updated_at = EXCLUDED.updated_at"
            ),
            {
                "agency_id": agency_id,
                **merged,
                "created_at": existing.created_at if existing else timestamp,
                "updated_at": timestamp,
            },
        )
        result = self.get(agency_id)
        assert result is not None
        return result


__all__ = ["ReelDefaultsRepository"]
