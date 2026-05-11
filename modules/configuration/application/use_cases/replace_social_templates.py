"""Replace the per-platform social templates for an agency.

The PUT endpoint replaces the whole block (no merge): every existing row
in `agency_social_templates` for the agency is dropped, and new rows are
inserted from the `templates` map. The verb `replace_*` reflects this.
"""

from __future__ import annotations

from dataclasses import dataclass

from modules.configuration.domain import SocialTemplate
from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
)
from shared.db import DatabaseUnitOfWork


@dataclass(frozen=True, slots=True)
class ReplaceSocialTemplatesInput:
    agency_id: str
    templates: dict[str, str]


class ReplaceSocialTemplatesUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        data: ReplaceSocialTemplatesInput,
    ) -> tuple[SocialTemplate, ...]:
        if uow.configuration is None:
            raise RuntimeError("The unit of work is not active.")
        agency_id = str(data.agency_id or "").strip()
        ensure_agency_exists(uow, agency_id)

        normalized: dict[str, str] = {}
        for key, value in (data.templates or {}).items():
            platform = str(key or "").strip().lower()
            if not platform:
                continue
            normalized[platform] = str(value or "")

        return uow.configuration.social_templates.replace_all_for_agency(
            agency_id=agency_id,
            templates=normalized,
        )


__all__ = ["ReplaceSocialTemplatesInput", "ReplaceSocialTemplatesUseCase"]
