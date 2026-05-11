"""FastAPI router for the agency brand-settings endpoints.

`/v1/admin/agencies/{agency_id}/brand` — read and update the agency
brand identity (colours, logo, watermark anchor, font).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ContextManager

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from apps.api.admin_auth import AdminAccessPolicy, authorize_admin_request
from apps.api.error_handlers import json_error
from modules.configuration.application.use_cases.read_brand_settings import (
    ReadBrandSettingsUseCase,
)
from modules.configuration.application.use_cases.update_brand_settings import (
    UpdateBrandSettingsInput,
    UpdateBrandSettingsUseCase,
)
from modules.configuration.domain import BrandSettings
from modules.configuration.transport.payloads.brand import BrandSettingsUpsertPayload
from shared.db import DatabaseUnitOfWork
from shared.errors import ApplicationError, ResourceNotFoundError, ValidationError

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]


def create_brand_router(
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    admin_access_policy: AdminAccessPolicy,
    read_brand_settings: ReadBrandSettingsUseCase | None = None,
    update_brand_settings: UpdateBrandSettingsUseCase | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix=admin_access_policy.base_path,
        tags=["Admin · Brand"],
    )
    read_brand_settings = read_brand_settings or ReadBrandSettingsUseCase()
    update_brand_settings = update_brand_settings or UpdateBrandSettingsUseCase()

    @router.get(
        "/agencies/{agency_id}/brand",
        summary="Read the agency's brand identity",
        description=(
            "Returns the brand slice of the agency configuration: colours, "
            "logo position, logo object keys, font family. Used by the "
            "agency-facing **Brand** tab."
        ),
    )
    async def read_admin_agency_brand_settings(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                record = read_brand_settings.execute(uow=uow, agency_id=agency_id)
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
                "agency_id": agency_id,
                "brand": _serialize_brand(record, agency_id=agency_id),
            },
        )

    @router.put(
        "/agencies/{agency_id}/brand",
        summary="Update the agency's brand identity",
        description=(
            "Replaces only the brand slice of the agency configuration. "
            "Fields omitted from the body preserve the previously stored "
            "value. Other configuration sections (defaults, automation, "
            "social_templates, music) are not touched."
        ),
    )
    async def update_admin_agency_brand_settings(
        agency_id: str,
        payload: BrandSettingsUpsertPayload,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                record = update_brand_settings.execute(
                    uow=uow,
                    data=UpdateBrandSettingsInput(
                        agency_id=agency_id,
                        primary_color=payload.primary_color,
                        secondary_color=payload.secondary_color,
                        logo_position=payload.logo_position,
                        logo_object_key=payload.logo_object_key,
                        intro_logo_object_key=payload.intro_logo_object_key,
                        font_family=payload.font_family,
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
                code=getattr(error, "code", "BRAND_SAVE_FAILED"),
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        return JSONResponse(
            status_code=200,
            content={
                "status": "saved",
                "agency_id": agency_id,
                "brand": _serialize_brand(record, agency_id=agency_id),
            },
        )

    return router


_DEFAULT_PRIMARY_COLOR = "#0F172A"
_DEFAULT_SECONDARY_COLOR = "#FFFFFF"
_DEFAULT_LOGO_POSITION = "top-right"


def _serialize_brand(
    record: BrandSettings | None,
    *,
    agency_id: str,
) -> dict[str, object]:
    if record is None:
        return {
            "agency_id": agency_id,
            "primary_color": _DEFAULT_PRIMARY_COLOR,
            "secondary_color": _DEFAULT_SECONDARY_COLOR,
            "logo_position": _DEFAULT_LOGO_POSITION,
            "logo_object_key": "",
            "intro_logo_object_key": "",
            "font_family": "",
            "created_at": "",
            "updated_at": "",
        }
    return {
        "agency_id": record.agency_id,
        "primary_color": record.primary_color or _DEFAULT_PRIMARY_COLOR,
        "secondary_color": record.secondary_color or _DEFAULT_SECONDARY_COLOR,
        "logo_position": record.logo_position or _DEFAULT_LOGO_POSITION,
        "logo_object_key": record.logo_object_key,
        "intro_logo_object_key": record.intro_logo_object_key,
        "font_family": record.font_family,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


__all__ = ["create_brand_router"]
