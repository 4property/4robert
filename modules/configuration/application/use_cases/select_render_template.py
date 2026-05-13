"""Select the render template pack used by an agency."""

from __future__ import annotations

from dataclasses import dataclass

from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
)
from modules.configuration.domain import RenderTemplate
from shared.db import DatabaseUnitOfWork
from shared.errors import ResourceNotFoundError, ValidationError


@dataclass(frozen=True, slots=True)
class SelectRenderTemplateInput:
    agency_id: str
    template_id: str


class SelectRenderTemplateUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        data: SelectRenderTemplateInput,
    ) -> RenderTemplate:
        if uow.configuration is None:
            raise RuntimeError("The unit of work is not active.")
        agency_id = str(data.agency_id or "").strip()
        template_id = str(data.template_id or "").strip()
        ensure_agency_exists(uow, agency_id)

        template = uow.configuration.render_templates.get(template_id)
        if template is None:
            raise ResourceNotFoundError(
                "The render template does not exist.",
                code="RENDER_TEMPLATE_NOT_FOUND",
                context={"template_id": template_id},
            )
        if not template.is_selectable:
            raise ValidationError(
                "The render template is not selectable.",
                code="RENDER_TEMPLATE_NOT_SELECTABLE",
                context={"template_id": template_id, "status": template.status},
            )
        uow.configuration.defaults.upsert(
            agency_id=agency_id,
            render_template_id=template.template_id,
        )
        return template


__all__ = ["SelectRenderTemplateInput", "SelectRenderTemplateUseCase"]
