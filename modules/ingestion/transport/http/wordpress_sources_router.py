"""Global WordPress sources admin router.

Powers ``/v1/admin/wordpress-sources`` and
``/v1/admin/wordpress-sources/{site_id}``. Replaces the legacy handlers
that lived in ``services/transport/http/server.py``. The agency-scoped
sibling lives in ``modules/ingestion/transport/http/sources_router.py``
(feature 4).

Each handler delegates to a use case under
``modules/ingestion/application/use_cases/`` and serializes the
``IngestionSourceWithAgency`` aggregate with the legacy WordPress source
shape so existing frontends keep working unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ContextManager

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from apps.api.admin_auth import AdminAccessPolicy, authorize_admin_request
from apps.api.error_handlers import json_error
from modules.ingestion.application.use_cases.inspect_wordpress_source_by_site_id import (
    InspectWordPressSourceBySiteIdUseCase,
)
from modules.ingestion.application.use_cases.list_global_wordpress_sources import (
    ListGlobalWordPressSourcesUseCase,
)
from modules.ingestion.application.use_cases.provision_wordpress_source import (
    ProvisionWordPressSourceInput,
    ProvisionWordPressSourceUseCase,
)
from modules.ingestion.domain import IngestionSourceWithAgency
from modules.ingestion.transport.payloads.wordpress_sources import (
    GlobalWordPressSourceUpsertPayload,
)
from shared.db import DatabaseUnitOfWork
from shared.errors import ApplicationError, ResourceNotFoundError, ValidationError

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]


def create_wordpress_sources_router(
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    admin_access_policy: AdminAccessPolicy,
    list_global_wordpress_sources: ListGlobalWordPressSourcesUseCase | None = None,
    inspect_wordpress_source_by_site_id: InspectWordPressSourceBySiteIdUseCase | None = None,
    provision_wordpress_source: ProvisionWordPressSourceUseCase | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix=admin_access_policy.base_path,
        tags=["Admin · Sources"],
    )
    list_global = list_global_wordpress_sources or ListGlobalWordPressSourcesUseCase()
    inspect_one = (
        inspect_wordpress_source_by_site_id or InspectWordPressSourceBySiteIdUseCase()
    )
    provision = provision_wordpress_source or ProvisionWordPressSourceUseCase()

    @router.get(
        "/wordpress-sources",
        summary="List every WordPress source across all agencies",
        description=(
            "Flat global view for source provisioning. The agency-scoped "
            "endpoint (`GET /v1/admin/agencies/{id}/sources`) is preferred "
            "for new flows."
        ),
    )
    async def list_admin_wordpress_sources(request: Request) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        with unit_of_work_factory() as uow:
            sources = list_global.execute(uow=uow)
        items = [_serialize_source(source) for source in sources]
        return JSONResponse(
            status_code=200,
            content={"items": items, "count": len(items)},
        )

    @router.get(
        "/wordpress-sources/{site_id}",
        summary="Get a single WordPress source by site_id",
        description=(
            "Looks up a WordPress source by the `site_id` (the value the "
            "`rest_domain` body field carries on the inbound webhook). "
            "Returns 404 with code `ADMIN_SOURCE_NOT_FOUND` if no source "
            "is registered for that site."
        ),
    )
    async def get_admin_wordpress_source(
        site_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                source = inspect_one.execute(uow=uow, site_id=site_id)
        except ValidationError as error:
            return json_error(
                400,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        if source is None:
            return json_error(
                404,
                "The wordpress source does not exist.",
                code="ADMIN_SOURCE_NOT_FOUND",
                hint="Create the site first with the admin provisioning endpoint.",
                details={"site_id": site_id},
            )
        return JSONResponse(
            status_code=200,
            content={"source": _serialize_source(source)},
        )

    @router.put(
        "/wordpress-sources/{site_id}",
        summary="Create or update a WordPress source by site_id",
        description=(
            "Upserts the WordPress source identified by `site_id`. Will "
            "create the agency on the fly if `agency_id` is omitted. "
            "Reassigning a source to a different agency is rejected."
        ),
    )
    async def upsert_admin_wordpress_source(
        site_id: str,
        payload: GlobalWordPressSourceUpsertPayload,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        update_webhook_secret = "webhook_secret" in payload.model_fields_set
        try:
            with unit_of_work_factory() as uow:
                result = provision.execute(
                    uow=uow,
                    data=ProvisionWordPressSourceInput(
                        site_id=site_id,
                        source_name=payload.source_name,
                        agency_id=payload.agency_id,
                        agency_name=payload.agency_name,
                        agency_slug=payload.agency_slug,
                        agency_timezone=payload.agency_timezone,
                        agency_status=payload.agency_status,
                        site_url=payload.site_url,
                        normalized_host=payload.normalized_host,
                        source_status=payload.source_status,
                        webhook_secret=payload.webhook_secret,
                        update_webhook_secret=update_webhook_secret,
                    ),
                )
        except ResourceNotFoundError as error:
            return json_error(
                404,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        except ValidationError as error:
            return json_error(
                400,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        except ApplicationError as error:
            return json_error(
                500,
                str(error),
                code=getattr(error, "code", "ADMIN_SOURCE_UPSERT_FAILED"),
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )

        status_code = 201 if result.created_source else 200
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "created" if result.created_source else "updated",
                "created_agency": result.created_agency,
                "updated_agency": result.updated_agency,
                "created_source": result.created_source,
                "updated_source": result.updated_source,
                "source": _serialize_source(result.source),
            },
        )

    return router


def _serialize_source(record: IngestionSourceWithAgency) -> dict[str, object]:
    """Render an ``IngestionSourceWithAgency`` with the legacy admin shape.

    The legacy response carried ``wordpress_source_id``, ``site_id``,
    ``site_url`` and ``normalized_host`` at the top level. They are
    reconstructed from the typed source columns + ``config_json`` so the
    frontend keeps working.
    """
    source = record.source
    config = dict(source.config or {})
    return {
        "wordpress_source_id": source.ingestion_source_id,
        "site_id": source.external_id,
        "name": source.name,
        "site_url": str(config.get("site_url") or ""),
        "normalized_host": str(config.get("normalized_host") or source.external_id or ""),
        "status": source.status,
        "has_webhook_secret": bool(source.has_secret),
        "last_event_at": source.last_event_at,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
        "agency": {
            "agency_id": source.agency_id,
            "name": record.agency_name,
            "slug": record.agency_slug,
            "timezone": record.agency_timezone,
            "status": record.agency_status,
        },
    }


__all__ = ["create_wordpress_sources_router"]
