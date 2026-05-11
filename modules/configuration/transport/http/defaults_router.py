"""FastAPI router for the agency reel-defaults endpoints.

`/v1/admin/agencies/{agency_id}/defaults` — read and update the global
reel rendering defaults. Defaults is the canonical owner of `platforms`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ContextManager

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from apps.api.admin_auth import AdminAccessPolicy, authorize_admin_request
from apps.api.error_handlers import json_error
from modules.configuration.application.use_cases.read_reel_defaults import (
    ReadReelDefaultsUseCase,
)
from modules.configuration.application.use_cases.update_reel_defaults import (
    UpdateReelDefaultsInput,
    UpdateReelDefaultsUseCase,
)
from modules.configuration.domain import ReelDefaults
from modules.configuration.transport.payloads.defaults import ReelDefaultsUpsertPayload
from shared.db import DatabaseUnitOfWork
from shared.errors import ApplicationError, ResourceNotFoundError, ValidationError

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]


_DEFAULT_PLATFORMS = (
    "tiktok",
    "instagram",
    "linkedin",
    "youtube",
    "facebook",
    "gbp",
)


def create_defaults_router(
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    admin_access_policy: AdminAccessPolicy,
    read_reel_defaults: ReadReelDefaultsUseCase | None = None,
    update_reel_defaults: UpdateReelDefaultsUseCase | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix=admin_access_policy.base_path,
        tags=["Admin · Defaults"],
    )
    read_reel_defaults = read_reel_defaults or ReadReelDefaultsUseCase()
    update_reel_defaults = update_reel_defaults or UpdateReelDefaultsUseCase()

    @router.get(
        "/agencies/{agency_id}/defaults",
        summary="Read the agency's reel rendering defaults",
        description=(
            "Returns the defaults slice — platforms, target duration, "
            "intro toggle, default music, caption template and the "
            "free-form `settings` document used by the **Defaults** tab."
        ),
    )
    async def read_admin_agency_reel_defaults(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                record = read_reel_defaults.execute(uow=uow, agency_id=agency_id)
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
                "defaults": _serialize_defaults(record, agency_id=agency_id),
            },
        )

    @router.put(
        "/agencies/{agency_id}/defaults",
        summary="Update the agency's reel rendering defaults",
        description=(
            "Replaces only the defaults slice. `platforms` is mirrored "
            "verbatim to the canonical column (defaults owns this field). "
            "`settings` is shallow-merged with the previously stored "
            "object so partial updates from one tab do not drop fields "
            "written by another."
        ),
    )
    async def update_admin_agency_reel_defaults(
        agency_id: str,
        payload: ReelDefaultsUpsertPayload,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                record = update_reel_defaults.execute(
                    uow=uow,
                    data=UpdateReelDefaultsInput(
                        agency_id=agency_id,
                        platforms=payload.platforms,
                        duration_seconds=payload.duration_seconds,
                        music_id=payload.music_id,
                        intro_enabled=payload.intro_enabled,
                        caption_template=payload.caption_template,
                        settings=payload.settings,
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
                code=getattr(error, "code", "REEL_DEFAULTS_SAVE_FAILED"),
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        return JSONResponse(
            status_code=200,
            content={
                "status": "saved",
                "agency_id": agency_id,
                "defaults": _serialize_defaults(record, agency_id=agency_id),
            },
        )

    return router


def _serialize_defaults(
    record: ReelDefaults | None,
    *,
    agency_id: str,
) -> dict[str, object]:
    if record is None:
        return {
            "agency_id": agency_id,
            "platforms": list(_DEFAULT_PLATFORMS),
            "duration_seconds": 30,
            "music_id": "",
            "intro_enabled": True,
            "caption_template": "",
            "settings": {},
            "created_at": "",
            "updated_at": "",
        }
    return {
        "agency_id": record.agency_id,
        "platforms": list(record.platforms),
        "duration_seconds": record.duration_seconds,
        "music_id": record.music_id,
        "intro_enabled": record.intro_enabled,
        "caption_template": record.caption_template,
        "settings": dict(record.settings or {}),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


__all__ = ["create_defaults_router"]
