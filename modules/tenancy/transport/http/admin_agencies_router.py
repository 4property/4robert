"""FastAPI router for `/v1/admin/agencies` management endpoints."""

from __future__ import annotations

from collections.abc import Callable
from typing import ContextManager

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from apps.api.admin_auth import AdminAccessPolicy, authorize_admin_request
from modules.tenancy.application.use_cases.decommission_agency import (
    DecommissionAgencyUseCase,
)
from modules.tenancy.application.use_cases.inspect_agency import InspectAgencyUseCase
from modules.tenancy.application.use_cases.list_agencies import ListAgenciesUseCase
from modules.tenancy.application.use_cases.reconfigure_agency import (
    ReconfigureAgencyInput,
    ReconfigureAgencyUseCase,
)
from modules.tenancy.application.use_cases.register_agency import (
    RegisterAgencyInput,
    RegisterAgencyUseCase,
)
from modules.tenancy.transport.payloads.agencies import (
    AdminAgencyCreatePayload,
    AdminAgencyUpdatePayload,
)
from shared.db import DatabaseUnitOfWork

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]

_DEFAULT_REEL_PROFILE_PLATFORMS = (
    "tiktok",
    "instagram",
    "linkedin",
    "youtube",
    "facebook",
    "gbp",
    "pinterest",
)


def create_admin_agencies_router(
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    admin_access_policy: AdminAccessPolicy,
    register_agency: RegisterAgencyUseCase | None = None,
    list_agencies: ListAgenciesUseCase | None = None,
    inspect_agency: InspectAgencyUseCase | None = None,
    reconfigure_agency: ReconfigureAgencyUseCase | None = None,
    decommission_agency: DecommissionAgencyUseCase | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix=admin_access_policy.base_path,
        tags=["Admin · Agencies"],
    )
    register_agency = register_agency or RegisterAgencyUseCase()
    list_agencies = list_agencies or ListAgenciesUseCase()
    inspect_agency = inspect_agency or InspectAgencyUseCase()
    reconfigure_agency = reconfigure_agency or ReconfigureAgencyUseCase()
    decommission_agency = decommission_agency or DecommissionAgencyUseCase()

    @router.get(
        "/agencies",
        summary="List every agency",
        description=(
            "Returns every agency known to the backend, together with the currently "
            "linked WordPress sources, the saved GoHighLevel connection, and the "
            "derived reel-profile snapshot."
        ),
    )
    async def list_admin_agencies(request: Request) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error

        with unit_of_work_factory() as uow:
            agencies = list_agencies.execute(uow=uow)
            items = [_serialize_agency_summary(uow=uow, agency=agency) for agency in agencies]
        return JSONResponse(status_code=200, content={"items": items, "count": len(items)})

    @router.post(
        "/agencies",
        summary="Create a new agency",
        description=(
            "Creates an empty agency. The slug is derived from `name` if not supplied. "
            "After creation the agency has no WordPress sources and no GHL connection."
        ),
    )
    async def create_admin_agency(
        payload: AdminAgencyCreatePayload,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error

        with unit_of_work_factory() as uow:
            agency = register_agency.execute(
                uow=uow,
                data=RegisterAgencyInput(
                    name=payload.name,
                    slug=payload.slug,
                    timezone=payload.timezone,
                    status=payload.status,
                ),
            )
        return JSONResponse(
            status_code=201,
            content={"status": "created", "agency": _serialize_agency(agency)},
        )

    @router.get(
        "/agencies/{agency_id}",
        summary="Get one agency with its sources, GHL connection and reel profile",
        description=(
            "Returns the agency record plus its WordPress sources, the GHL connection "
            "and the reel profile snapshot currently persisted for that tenant."
        ),
    )
    async def get_admin_agency(agency_id: str, request: Request) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error

        with unit_of_work_factory() as uow:
            agency = inspect_agency.execute(uow=uow, agency_id=agency_id)
            sources, ghl_connection, reel_profile = _load_agency_supporting_payloads(
                uow=uow,
                agency_id=agency.agency_id,
            )
        return JSONResponse(
            status_code=200,
            content={
                "agency": _serialize_agency(agency),
                "sources": sources,
                "ghl_connection": ghl_connection,
                "reel_profile": reel_profile,
            },
        )

    @router.patch(
        "/agencies/{agency_id}",
        summary="Update agency name / slug / timezone / status",
        description=(
            "Partial update: fields not present in the body keep their current value."
        ),
    )
    async def update_admin_agency(
        agency_id: str,
        payload: AdminAgencyUpdatePayload,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error

        with unit_of_work_factory() as uow:
            agency = reconfigure_agency.execute(
                uow=uow,
                data=ReconfigureAgencyInput(
                    agency_id=agency_id,
                    name=payload.name,
                    slug=payload.slug,
                    timezone=payload.timezone,
                    status=payload.status,
                ),
            )
        return JSONResponse(
            status_code=200,
            content={"status": "updated", "agency": _serialize_agency(agency)},
        )

    @router.delete(
        "/agencies/{agency_id}",
        summary="Delete an agency",
        description=(
            "Deletes the agency and relies on FK cascades for linked sources, "
            "connections and configuration rows."
        ),
    )
    async def delete_admin_agency(agency_id: str, request: Request) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error

        with unit_of_work_factory() as uow:
            decommission_agency.execute(uow=uow, agency_id=agency_id)
        return JSONResponse(
            status_code=200,
            content={"status": "deleted", "agency_id": agency_id},
        )

    return router


def _serialize_agency(agency: object) -> dict[str, object]:
    return {
        "agency_id": getattr(agency, "agency_id", ""),
        "name": getattr(agency, "name", ""),
        "slug": getattr(agency, "slug", ""),
        "timezone": getattr(agency, "timezone", ""),
        "status": getattr(agency, "status", ""),
        "created_at": getattr(agency, "created_at", None),
        "updated_at": getattr(agency, "updated_at", None),
    }


def _serialize_agency_summary(
    *,
    uow: DatabaseUnitOfWork,
    agency: object,
) -> dict[str, object]:
    sources, ghl_connection, reel_profile = _load_agency_supporting_payloads(
        uow=uow,
        agency_id=str(getattr(agency, "agency_id", "")),
    )
    return {
        **_serialize_agency(agency),
        "source_count": len(sources),
        "sources": sources,
        "ghl_connection": ghl_connection,
        "reel_profile": reel_profile,
    }


def _load_agency_supporting_payloads(
    *,
    uow: DatabaseUnitOfWork,
    agency_id: str,
) -> tuple[list[dict[str, object]], dict[str, object] | None, dict[str, object] | None]:
    sources = []
    if uow.ingestion is not None:
        sources = [
            _serialize_wordpress_source_details(source)
            for source in uow.ingestion.sources.list_for_agency(agency_id)
        ]

    ghl_connection = None
    if uow.publishing is not None:
        connection = uow.publishing.connections.get_with_secrets(
            agency_id=agency_id,
            provider="gohighlevel",
        )
        ghl_connection = _serialize_gohighlevel_connection(connection)

    reel_profile = None
    if uow.configuration is not None:
        reel_profile = _serialize_reel_profile(
            agency_id=agency_id,
            brand=uow.configuration.brand.get(agency_id),
            defaults=uow.configuration.defaults.get(agency_id),
            automation=uow.configuration.automation.get(agency_id),
        )

    return sources, ghl_connection, reel_profile


def _serialize_gohighlevel_connection(connection: object | None) -> dict[str, object] | None:
    if connection is None:
        return None
    config = dict(getattr(connection, "config", {}) or {})
    secrets = dict(getattr(connection, "secrets", {}) or {})
    return {
        "connection_id": getattr(connection, "connection_id", ""),
        "agency_id": getattr(connection, "agency_id", ""),
        "location_id": getattr(connection, "external_id", ""),
        "user_id": str(config.get("user_id") or ""),
        "has_access_token": bool(str(secrets.get("access_token") or "").strip()),
        "has_refresh_token": bool(str(secrets.get("refresh_token") or "").strip()),
        "expires_at": str(secrets.get("expires_at") or config.get("expires_at") or ""),
        "status": getattr(connection, "status", ""),
        "created_at": getattr(connection, "created_at", None),
        "updated_at": getattr(connection, "updated_at", None),
    }


def _serialize_reel_profile(
    *,
    agency_id: str,
    brand: object | None,
    defaults: object | None,
    automation: object | None,
) -> dict[str, object] | None:
    if brand is None and defaults is None and automation is None:
        return None
    created_at = (
        getattr(defaults, "created_at", "")
        or getattr(brand, "created_at", "")
        or getattr(automation, "created_at", "")
    )
    updated_at = (
        getattr(defaults, "updated_at", "")
        or getattr(brand, "updated_at", "")
        or getattr(automation, "updated_at", "")
    )
    return {
        "profile_id": agency_id,
        "agency_id": agency_id,
        "name": "Default",
        "platforms": list(getattr(defaults, "platforms", ()) or _DEFAULT_REEL_PROFILE_PLATFORMS),
        "duration_seconds": int(getattr(defaults, "duration_seconds", 30) or 30),
        "music_id": str(getattr(defaults, "music_id", "") or ""),
        "intro_enabled": bool(
            getattr(defaults, "intro_enabled", True) if defaults is not None else True
        ),
        "logo_position": str(getattr(brand, "logo_position", "top-right") or "top-right"),
        "brand_primary_color": str(
            getattr(brand, "primary_color", "#0F172A") or "#0F172A"
        ),
        "brand_secondary_color": str(
            getattr(brand, "secondary_color", "#FFFFFF") or "#FFFFFF"
        ),
        "caption_template": str(getattr(defaults, "caption_template", "") or ""),
        "approval_required": bool(
            getattr(automation, "approval_required", False)
            if automation is not None
            else False
        ),
        "extra_settings": dict(getattr(defaults, "settings", {}) or {}),
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _serialize_wordpress_source_details(source: object) -> dict[str, object]:
    config = dict(getattr(getattr(source, "source", None), "config", {}) or {})
    source_row = getattr(source, "source", source)
    # TODO Phase 2 feature 4: unify this serializer with the ingestion router.
    return {
        "wordpress_source_id": getattr(source_row, "ingestion_source_id", ""),
        "site_id": getattr(source_row, "external_id", ""),
        "name": getattr(source_row, "name", ""),
        "site_url": str(config.get("site_url") or ""),
        "normalized_host": str(
            config.get("normalized_host") or getattr(source_row, "external_id", "")
        ),
        "status": getattr(source_row, "status", ""),
        "has_webhook_secret": bool(getattr(source_row, "has_secret", False)),
        "last_event_at": getattr(source_row, "last_event_at", None),
        "created_at": getattr(source_row, "created_at", None),
        "updated_at": getattr(source_row, "updated_at", None),
        "agency": {
            "agency_id": getattr(source_row, "agency_id", ""),
            "name": getattr(source, "agency_name", ""),
            "slug": getattr(source, "agency_slug", ""),
            "timezone": getattr(source, "agency_timezone", ""),
            "status": getattr(source, "agency_status", ""),
        },
    }


__all__ = ["create_admin_agencies_router"]
