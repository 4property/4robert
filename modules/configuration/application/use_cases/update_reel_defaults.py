"""Update the reel-defaults slice of an agency configuration.

Defaults is the **canonical owner** of `platforms` (mirrored to the
`agency_reel_defaults.platforms` column). Automation rules **do not**
write `platforms`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from modules.configuration.domain import ReelDefaults
from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
)
from shared.db import DatabaseUnitOfWork


@dataclass(frozen=True, slots=True)
class UpdateReelDefaultsInput:
    agency_id: str
    platforms: Iterable[str] | None = None
    duration_seconds: int | None = None
    music_id: str | None = None
    intro_enabled: bool | None = None
    caption_template: str | None = None
    settings: Mapping[str, Any] | None = field(default=None)


class UpdateReelDefaultsUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        data: UpdateReelDefaultsInput,
    ) -> ReelDefaults:
        if uow.configuration is None:
            raise RuntimeError("The unit of work is not active.")
        agency_id = str(data.agency_id or "").strip()
        ensure_agency_exists(uow, agency_id)

        # The frontend sends a free-form `settings` object (INITIAL_DEFAULTS
        # shape). It is merged with the previously stored object so partial
        # updates from one tab don't drop fields written by another tab.
        merged_settings: Mapping[str, Any] | None = None
        if data.settings is not None:
            existing = uow.configuration.defaults.get(agency_id)
            existing_settings = dict(existing.settings) if existing else {}
            merged_settings = {**existing_settings, **dict(data.settings)}

        return uow.configuration.defaults.upsert(
            agency_id=agency_id,
            platforms=data.platforms,
            duration_seconds=data.duration_seconds,
            music_id=data.music_id,
            intro_enabled=data.intro_enabled,
            caption_template=data.caption_template,
            settings=merged_settings,
        )


__all__ = ["UpdateReelDefaultsInput", "UpdateReelDefaultsUseCase"]
