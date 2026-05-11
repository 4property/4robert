"""Aggregated reel-profile admin router.

Exposes the legacy "raw" reel-profile endpoints used by the admin
**Reel settings** drawer. Replaces the handlers that lived in
``services/transport/http/server.py``. Persistence is fanned out to the
typed configuration tables behind ``uow.configuration.{brand,defaults,
automation,social_templates,music}``; no legacy ``ReelProfileStore`` is
consulted.

Prefer the per-section endpoints under ``/v1/admin/agencies/{id}/...``
(``/brand``, ``/defaults``, ``/automation``, ``/social-templates``,
``/music``) for any flow that only needs to edit a single concern. The
aggregated endpoint exists only because the **Reel settings** drawer
still consumes a single document.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ContextManager

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from apps.api.admin_auth import AdminAccessPolicy, authorize_admin_request
from apps.api.error_handlers import json_error
from modules.configuration.application.use_cases.read_aggregated_reel_profile import (
    ReadAggregatedReelProfileUseCase,
)
from modules.configuration.application.use_cases.update_aggregated_reel_profile import (
    UpdateAggregatedReelProfileInput,
    UpdateAggregatedReelProfileUseCase,
)
from modules.configuration.transport.payloads.reel_profile import (
    ReelProfileUpsertPayload,
)
from shared.db import DatabaseUnitOfWork
from shared.errors import ApplicationError, ResourceNotFoundError, ValidationError

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]


def create_reel_profile_router(
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    admin_access_policy: AdminAccessPolicy,
    read_aggregated_reel_profile: ReadAggregatedReelProfileUseCase | None = None,
    update_aggregated_reel_profile: UpdateAggregatedReelProfileUseCase | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix=admin_access_policy.base_path,
        tags=["Admin · Reel profile (raw)"],
    )
    read_use_case = read_aggregated_reel_profile or ReadAggregatedReelProfileUseCase()
    update_use_case = (
        update_aggregated_reel_profile or UpdateAggregatedReelProfileUseCase()
    )

    @router.get(
        "/agencies/{agency_id}/reel-profile",
        summary="Read the aggregated reel profile for an agency",
        description=(
            "Returns the agency configuration assembled into the legacy "
            "`reel_profiles` shape (brand + defaults + automation + "
            "social templates + music tracks). Prefer the per-section "
            "endpoints — `/brand`, `/defaults`, `/automation`, "
            "`/social-templates`, `/music` — when you only need a single "
            "concern."
        ),
    )
    async def get_admin_agency_reel_profile(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                profile = read_use_case.execute(uow=uow, agency_id=agency_id)
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
                "reel_profile": profile.to_public_dict() if profile else None,
            },
        )

    @router.put(
        "/agencies/{agency_id}/reel-profile",
        summary="Update the aggregated reel profile for an agency",
        description=(
            "Accepts the legacy aggregated payload and fans the update "
            "out to the typed sections (`brand`, `defaults`, "
            "`automation`). Fields omitted from the body preserve the "
            "previously stored value. `extra_settings`, when present, "
            "replaces the free-form `agency_reel_defaults.settings` "
            "document wholesale."
        ),
    )
    async def upsert_admin_agency_reel_profile(
        agency_id: str,
        payload: ReelProfileUpsertPayload,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                profile = update_use_case.execute(
                    uow=uow,
                    data=UpdateAggregatedReelProfileInput(
                        agency_id=agency_id,
                        name=payload.name,
                        platforms=payload.platforms,
                        duration_seconds=payload.duration_seconds,
                        music_id=payload.music_id,
                        intro_enabled=payload.intro_enabled,
                        logo_position=payload.logo_position,
                        brand_primary_color=payload.brand_primary_color,
                        brand_secondary_color=payload.brand_secondary_color,
                        caption_template=payload.caption_template,
                        approval_required=payload.approval_required,
                        extra_settings=payload.extra_settings,
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
                code=getattr(error, "code", "REEL_PROFILE_SAVE_FAILED"),
                hint=error.hint,
            )
        return JSONResponse(
            status_code=200,
            content={
                "status": "saved",
                "reel_profile": profile.to_public_dict(),
            },
        )

    return router


__all__ = ["create_reel_profile_router"]
