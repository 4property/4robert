"""FastAPI router for `/v1/admin/agencies/{agency_id}/sources` (ingestion sources)."""

from __future__ import annotations

from collections.abc import Callable
from typing import ContextManager

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from apps.api.admin_auth import AdminAccessPolicy, authorize_admin_request
from modules.ingestion.application.use_cases.decommission_ingestion_source import (
    DecommissionIngestionSourceUseCase,
)
from modules.ingestion.application.use_cases.inspect_ingestion_source import (
    InspectIngestionSourceUseCase,
)
from modules.ingestion.application.use_cases.list_ingestion_sources import (
    ListIngestionSourcesUseCase,
)
from modules.ingestion.application.use_cases.reconfigure_ingestion_source import (
    ReconfigureIngestionSourceInput,
    ReconfigureIngestionSourceUseCase,
)
from modules.ingestion.application.use_cases.register_ingestion_source import (
    RegisterIngestionSourceInput,
    RegisterIngestionSourceUseCase,
)
from modules.ingestion.domain import IngestionSource, IngestionSourceWithAgency
from modules.ingestion.transport.payloads.sources import (
    IngestionSourceCreatePayload,
    IngestionSourceUpdatePayload,
)
from shared.db import DatabaseUnitOfWork

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]


def create_sources_router(
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    admin_access_policy: AdminAccessPolicy,
    register_ingestion_source: RegisterIngestionSourceUseCase | None = None,
    list_ingestion_sources: ListIngestionSourcesUseCase | None = None,
    inspect_ingestion_source: InspectIngestionSourceUseCase | None = None,
    reconfigure_ingestion_source: ReconfigureIngestionSourceUseCase | None = None,
    decommission_ingestion_source: DecommissionIngestionSourceUseCase | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix=admin_access_policy.base_path,
        tags=["Admin - Sources"],
    )
    register_ingestion_source = register_ingestion_source or RegisterIngestionSourceUseCase()
    list_ingestion_sources = list_ingestion_sources or ListIngestionSourcesUseCase()
    inspect_ingestion_source = inspect_ingestion_source or InspectIngestionSourceUseCase()
    reconfigure_ingestion_source = (
        reconfigure_ingestion_source or ReconfigureIngestionSourceUseCase()
    )
    decommission_ingestion_source = (
        decommission_ingestion_source or DecommissionIngestionSourceUseCase()
    )

    @router.post(
        "/agencies/{agency_id}/sources",
        summary="Register a new ingestion source for an agency",
        description=(
            "Creates an ingestion source bound to the agency. The "
            "`site_id` is the value WordPress posts as `rest_domain` "
            "in webhook bodies."
        ),
    )
    async def register_ingestion_source_endpoint(
        agency_id: str,
        payload: IngestionSourceCreatePayload,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error

        with unit_of_work_factory() as uow:
            source = register_ingestion_source.execute(
                uow=uow,
                data=RegisterIngestionSourceInput(
                    agency_id=agency_id,
                    name=payload.name,
                    external_id=payload.site_id,
                    kind=payload.kind,
                    site_url=payload.site_url,
                    normalized_host=payload.normalized_host,
                    status=payload.status,
                    secret=payload.webhook_secret or "",
                ),
            )
            agency = uow.tenancy.agencies.get_by_id(agency_id)  # type: ignore[union-attr]
        return JSONResponse(
            status_code=201,
            content={
                "status": "created",
                "source": _serialize_source(source=source, agency=agency),
            },
        )

    @router.get(
        "/agencies/{agency_id}/sources",
        summary="List the ingestion sources of an agency",
    )
    async def list_ingestion_sources_endpoint(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error

        with unit_of_work_factory() as uow:
            items = list_ingestion_sources.execute(uow=uow, agency_id=agency_id)
        serialized = [_serialize_source_with_agency(item) for item in items]
        return JSONResponse(
            status_code=200,
            content={"items": serialized, "count": len(serialized)},
        )

    @router.get(
        "/agencies/{agency_id}/sources/{ingestion_source_id}",
        summary="Inspect a single ingestion source",
    )
    async def inspect_ingestion_source_endpoint(
        agency_id: str,
        ingestion_source_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error

        with unit_of_work_factory() as uow:
            item = inspect_ingestion_source.execute(
                uow=uow,
                agency_id=agency_id,
                ingestion_source_id=ingestion_source_id,
            )
        return JSONResponse(
            status_code=200,
            content={"source": _serialize_source_with_agency(item)},
        )

    @router.put(
        "/agencies/{agency_id}/sources/{ingestion_source_id}",
        summary="Reconfigure an ingestion source",
    )
    async def reconfigure_ingestion_source_endpoint(
        agency_id: str,
        ingestion_source_id: str,
        payload: IngestionSourceUpdatePayload,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error

        update_secret = "webhook_secret" in payload.model_fields_set

        with unit_of_work_factory() as uow:
            source = reconfigure_ingestion_source.execute(
                uow=uow,
                data=ReconfigureIngestionSourceInput(
                    agency_id=agency_id,
                    ingestion_source_id=ingestion_source_id,
                    name=payload.name,
                    site_url=payload.site_url,
                    normalized_host=payload.normalized_host,
                    status=payload.status,
                    secret=payload.webhook_secret,
                    update_secret=update_secret,
                ),
            )
            agency = uow.tenancy.agencies.get_by_id(agency_id)  # type: ignore[union-attr]
        return JSONResponse(
            status_code=200,
            content={
                "status": "updated",
                "source": _serialize_source(source=source, agency=agency),
            },
        )

    @router.delete(
        "/agencies/{agency_id}/sources/{ingestion_source_id}",
        summary="Decommission an ingestion source",
    )
    async def decommission_ingestion_source_endpoint(
        agency_id: str,
        ingestion_source_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error

        with unit_of_work_factory() as uow:
            decommission_ingestion_source.execute(
                uow=uow,
                agency_id=agency_id,
                ingestion_source_id=ingestion_source_id,
            )
        return JSONResponse(
            status_code=200,
            content={
                "status": "deleted",
                "agency_id": agency_id,
                "ingestion_source_id": ingestion_source_id,
            },
        )

    return router


def _serialize_source(
    *,
    source: IngestionSource,
    agency: object | None,
) -> dict[str, object]:
    config = dict(source.config or {})
    return {
        "ingestion_source_id": source.ingestion_source_id,
        "wordpress_source_id": source.ingestion_source_id,
        "site_id": source.external_id,
        "external_id": source.external_id,
        "kind": source.kind,
        "name": source.name,
        "site_url": str(config.get("site_url") or f"https://{source.external_id}"),
        "normalized_host": str(
            config.get("normalized_host") or source.external_id
        ),
        "status": source.status,
        "has_webhook_secret": bool(source.has_secret),
        "last_event_at": source.last_event_at,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
        "agency": _serialize_agency_block(agency=agency, agency_id=source.agency_id),
    }


def _serialize_source_with_agency(item: IngestionSourceWithAgency) -> dict[str, object]:
    source = item.source
    config = dict(source.config or {})
    return {
        "ingestion_source_id": source.ingestion_source_id,
        "wordpress_source_id": source.ingestion_source_id,
        "site_id": source.external_id,
        "external_id": source.external_id,
        "kind": source.kind,
        "name": source.name,
        "site_url": str(config.get("site_url") or f"https://{source.external_id}"),
        "normalized_host": str(
            config.get("normalized_host") or source.external_id
        ),
        "status": source.status,
        "has_webhook_secret": bool(source.has_secret),
        "last_event_at": source.last_event_at,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
        "agency": {
            "agency_id": source.agency_id,
            "name": item.agency_name,
            "slug": item.agency_slug,
            "timezone": item.agency_timezone,
            "status": item.agency_status,
        },
    }


def _serialize_agency_block(
    *,
    agency: object | None,
    agency_id: str,
) -> dict[str, object]:
    if agency is None:
        return {
            "agency_id": agency_id,
            "name": "",
            "slug": "",
            "timezone": "",
            "status": "",
        }
    return {
        "agency_id": getattr(agency, "agency_id", agency_id),
        "name": getattr(agency, "name", ""),
        "slug": getattr(agency, "slug", ""),
        "timezone": getattr(agency, "timezone", ""),
        "status": getattr(agency, "status", ""),
    }


__all__ = ["create_sources_router"]
