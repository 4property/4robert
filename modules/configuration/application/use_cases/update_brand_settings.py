"""Update the brand slice of an agency configuration.

Writes directly to `agency_brand_settings` via
`uow.configuration.brand.upsert(...)`. Other configuration sections
(defaults, automation, social_templates, music) are not touched.
"""

from __future__ import annotations

from dataclasses import dataclass

from modules.configuration.domain import BrandSettings
from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
)
from shared.db import DatabaseUnitOfWork


@dataclass(frozen=True, slots=True)
class UpdateBrandSettingsInput:
    agency_id: str
    primary_color: str | None = None
    secondary_color: str | None = None
    logo_position: str | None = None
    logo_object_key: str | None = None
    intro_logo_object_key: str | None = None
    font_family: str | None = None


class UpdateBrandSettingsUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        data: UpdateBrandSettingsInput,
    ) -> BrandSettings:
        if uow.configuration is None:
            raise RuntimeError("The unit of work is not active.")
        agency_id = str(data.agency_id or "").strip()
        ensure_agency_exists(uow, agency_id)
        return uow.configuration.brand.upsert(
            agency_id=agency_id,
            primary_color=data.primary_color,
            secondary_color=data.secondary_color,
            logo_position=data.logo_position,
            logo_object_key=data.logo_object_key,
            intro_logo_object_key=data.intro_logo_object_key,
            font_family=data.font_family,
        )


__all__ = ["UpdateBrandSettingsInput", "UpdateBrandSettingsUseCase"]
