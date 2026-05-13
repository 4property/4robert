"""FastAPI router for agency render-template catalog selection."""

from __future__ import annotations

from collections.abc import Callable
from typing import ContextManager

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from apps.api.admin_auth import AdminAccessPolicy, authorize_admin_request
from apps.api.error_handlers import json_error
from modules.configuration.application.use_cases.list_render_templates import (
    ListRenderTemplatesUseCase,
)
from modules.configuration.application.use_cases.select_render_template import (
    SelectRenderTemplateInput,
    SelectRenderTemplateUseCase,
)
from modules.configuration.domain import RenderTemplate, RenderTemplatePreviewImage
from modules.configuration.transport.payloads.render_templates import (
    RenderTemplateSelectPayload,
)
from shared.db import DatabaseUnitOfWork
from shared.errors import ApplicationError, ResourceNotFoundError, ValidationError

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]


def create_render_templates_router(
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    admin_access_policy: AdminAccessPolicy,
    list_render_templates: ListRenderTemplatesUseCase | None = None,
    select_render_template: SelectRenderTemplateUseCase | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix=admin_access_policy.base_path,
        tags=["Admin · Render templates"],
    )
    list_use_case = list_render_templates or ListRenderTemplatesUseCase()
    select_use_case = select_render_template or SelectRenderTemplateUseCase()

    @router.get(
        "/agencies/{agency_id}/render-templates",
        summary="List render template packs for an agency",
    )
    async def list_admin_agency_render_templates(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                result = list_use_case.execute(uow=uow, agency_id=agency_id)
        except ResourceNotFoundError as error:
            return json_error(
                404,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        return JSONResponse(
            status_code=200,
            content={
                "agency_id": result.agency_id,
                "current_template_id": result.current_template_id,
                "items": [
                    _serialize_template(
                        item,
                        selected=item.template_id == result.current_template_id,
                    )
                    for item in result.items
                ],
            },
        )

    @router.put(
        "/agencies/{agency_id}/render-template",
        summary="Select the render template pack for an agency",
    )
    async def select_admin_agency_render_template(
        agency_id: str,
        payload: RenderTemplateSelectPayload,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                template = select_use_case.execute(
                    uow=uow,
                    data=SelectRenderTemplateInput(
                        agency_id=agency_id,
                        template_id=payload.template_id,
                    ),
                )
        except ValidationError as error:
            return json_error(
                400,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        except ResourceNotFoundError as error:
            return json_error(
                404,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        except ApplicationError as error:
            return json_error(
                500,
                str(error),
                code=getattr(error, "code", "RENDER_TEMPLATE_SAVE_FAILED"),
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        return JSONResponse(
            status_code=200,
            content={
                "status": "saved",
                "agency_id": agency_id,
                "render_template": _serialize_template(template, selected=True),
            },
        )

    return router


def _serialize_preview_image(image: RenderTemplatePreviewImage) -> dict[str, object]:
    return {
        "kind": image.kind,
        "image_url": image.image_url,
        "alt": image.alt,
    }


def _serialize_template(
    template: RenderTemplate,
    *,
    selected: bool,
) -> dict[str, object]:
    return {
        "template_id": template.template_id,
        "display_name": template.display_name,
        "description": template.description,
        "status": template.status,
        "sort_order": template.sort_order,
        "preview_images": [
            _serialize_preview_image(image) for image in template.preview_images
        ],
        "layout_variant": template.layout_variant,
        "selected": selected,
    }


__all__ = ["create_render_templates_router"]
