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
        # Hotfix 2026-05-15: distinguish "key omitted from the JSON body"
        # (preserve the existing column) from "key sent as null" (clear
        # the override). Pydantic collapses both onto ``None``, so we
        # consult ``model_dump(exclude_unset=True)`` for the set of
        # explicitly supplied keys and forward it to the use case.
        fields_present = frozenset(payload.model_dump(exclude_unset=True).keys())
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
                        fields_present=fields_present,
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


# Hotfix 2026-05-15: neutral grey defaults emitted when the agency
# has not yet saved a brand row. The frontend pickers show these as a
# starting point and the user can then change them; the renderer
# applies the same greys (``_SIDE_BANNER_PANEL_DEFAULT`` in
# ``poster.py``/``render_reel.py`` and ``_SIDE_BANNER_RIBBON_BACKGROUND``
# in ``preparation.py``) when ``side_banner_panel_color`` /
# ``side_banner_ribbon_background_color`` are absent. The earlier
# ``#0F172A`` / ``#FFFFFF`` defaults were a hangover from the
# pre-Reset contract and hid the "unconfigured" state from the user.
_DEFAULT_PRIMARY_COLOR = "#374151"
_DEFAULT_SECONDARY_COLOR = "#9CA3AF"
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
    # Hotfix 2026-05-15: when a colour / font column is an empty string
    # the record exists but the agency has explicitly cleared the
    # override (via the "Reset to default" affordance on the frontend).
    # The previous serializer coerced that empty string into the
    # ``_DEFAULT_PRIMARY_COLOR`` hex, which made the cleared state
    # indistinguishable from a real configured value on the client.
    # Emit the empty string verbatim so the frontend's ``brand?.field
    # || null`` hydration switches the UI to "Using default" and the
    # renderer's cascade (brand → webhook → hardcoded) is honoured.
    # ``logo_position`` keeps the legacy fallback because there is no
    # UI to reset it independently — the column always carries a real
    # value once any field is upserted.
    return {
        "agency_id": record.agency_id,
        "primary_color": record.primary_color,
        "secondary_color": record.secondary_color,
        "logo_position": record.logo_position or _DEFAULT_LOGO_POSITION,
        "logo_object_key": record.logo_object_key,
        "intro_logo_object_key": record.intro_logo_object_key,
        "font_family": record.font_family,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


__all__ = ["create_brand_router"]
