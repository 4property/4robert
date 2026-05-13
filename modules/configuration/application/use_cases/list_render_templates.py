"""List DB-backed render template packs for an agency."""

from __future__ import annotations

from dataclasses import dataclass

from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
)
from modules.configuration.domain import RenderTemplate
from shared.db import DatabaseUnitOfWork


@dataclass(frozen=True, slots=True)
class AgencyRenderTemplateList:
    agency_id: str
    current_template_id: str
    items: tuple[RenderTemplate, ...]


class ListRenderTemplatesUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
    ) -> AgencyRenderTemplateList:
        if uow.configuration is None:
            raise RuntimeError("The unit of work is not active.")
        normalized_agency_id = str(agency_id or "").strip()
        ensure_agency_exists(uow, normalized_agency_id)

        defaults = uow.configuration.defaults.get(normalized_agency_id)
        requested_template_id = (
            getattr(defaults, "render_template_id", "classic")
            if defaults is not None
            else "classic"
        )
        items = uow.configuration.render_templates.list_all()
        known_ids = {item.template_id for item in items}
        current_template_id = (
            requested_template_id if requested_template_id in known_ids else "classic"
        )
        return AgencyRenderTemplateList(
            agency_id=normalized_agency_id,
            current_template_id=current_template_id,
            items=items,
        )


__all__ = ["AgencyRenderTemplateList", "ListRenderTemplatesUseCase"]
