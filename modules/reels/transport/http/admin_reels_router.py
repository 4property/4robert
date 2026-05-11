"""FastAPI router for the admin "Reels" surface.

Endpoints under `/v1/admin/agencies/{agency_id}/reels/*`:

- `GET    /`                               → list recent reels (use case `list_reels`)
- `GET    /{site_id}/{property_id}`        → reel detail (use case `inspect_reel`)
- `GET    /{site_id}/{property_id}/video`  → stream MP4 (range, transport helper)
- `GET    /{site_id}/{property_id}/images` → list source photos (transport helper)
- `GET    /{site_id}/{property_id}/images/{position}/file`
                                            → stream one source image (transport helper)
- `GET    /{site_id}/{property_id}/manifest`
                                            → JSON manifest (transport helper)
- `POST   /{site_id}/{property_id}/approve`
                                            → enqueue publish job (use case `regenerate_reel`).
                                              Path stays `/approve` for frontend compat.
- `POST   /{site_id}/{property_id}/reject` → mark workflow rejected (use case `reject_reel`)

The four asset GETs (video / images / image file / manifest) are pure
transport helpers (read a file, stream bytes); they do not warrant a
use case. They live in `admin_reels_assets.py` and are attached here
via :func:`register_admin_reel_asset_routes`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import ContextManager

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from apps.api.admin_auth import AdminAccessPolicy, authorize_admin_request
from apps.api.error_handlers import json_error
from modules.reels.application.use_cases.inspect_reel import InspectReelUseCase
from modules.reels.application.use_cases.list_reels import ListReelsUseCase
from modules.reels.application.use_cases.regenerate_reel import (
    RegenerateReelUseCase,
)
from modules.reels.application.use_cases.reject_reel import RejectReelUseCase
from modules.reels.transport.http.admin_reels_assets import (
    _application_error_response,
    _resolve_workspace_path,
    _resource_not_found_response,
    _serialize_agency_reel,
    register_admin_reel_asset_routes,
)
from shared.db import DatabaseUnitOfWork
from shared.errors import ApplicationError, ResourceNotFoundError, ValidationError

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]


def create_admin_reels_router(
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    admin_access_policy: AdminAccessPolicy,
    workspace_dir: str | Path,
    job_max_attempts: int,
    default_platforms: tuple[str, ...] = (),
    list_reels: ListReelsUseCase | None = None,
    inspect_reel: InspectReelUseCase | None = None,
    regenerate_reel: RegenerateReelUseCase | None = None,
    reject_reel: RejectReelUseCase | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix=admin_access_policy.base_path,
        tags=["Admin · Content"],
    )
    list_reels_use_case = list_reels or ListReelsUseCase()
    inspect_reel_use_case = inspect_reel or InspectReelUseCase()
    regenerate_reel_use_case = regenerate_reel or RegenerateReelUseCase(
        job_max_attempts=job_max_attempts,
        default_platforms=default_platforms,
    )
    reject_reel_use_case = reject_reel or RejectReelUseCase()
    resolved_workspace_dir = Path(workspace_dir).expanduser().resolve()

    @router.get(
        "/agencies/{agency_id}/reels",
        summary="List the agency's recent reels",
        description=(
            "Returns the most recent reels for the agency, joining the "
            "`properties` row, the latest `reels` row, and the most recent "
            "`media_revisions` row. Used by the agency Reels dashboard."
        ),
    )
    async def list_admin_agency_reels(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            limit = int(request.query_params.get("limit") or 50)
        except ValueError:
            limit = 50
        try:
            with unit_of_work_factory() as uow:
                items = list_reels_use_case.execute(
                    uow=uow, agency_id=agency_id, limit=limit
                )
        except ResourceNotFoundError as error:
            return _resource_not_found_response(error)
        return JSONResponse(
            status_code=200,
            content={
                "items": [_serialize_agency_reel(item) for item in items],
                "count": len(items),
            },
        )

    @router.get(
        "/agencies/{agency_id}/reels/{site_id}/{source_property_id}",
        summary="Get one reel for the agency",
        description=(
            "Same shape as one item from the listing endpoint, plus a "
            "`has_video` flag and a relative `video_url` to stream the "
            "rendered MP4."
        ),
    )
    async def get_admin_agency_reel(
        agency_id: str,
        site_id: str,
        source_property_id: int,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                item = inspect_reel_use_case.execute(
                    uow=uow,
                    agency_id=agency_id,
                    site_id=site_id,
                    source_property_id=source_property_id,
                )
        except ResourceNotFoundError as error:
            return _resource_not_found_response(error)
        body = _serialize_agency_reel(item)
        video_path = _resolve_workspace_path(
            resolved_workspace_dir, item.revision_media_path
        )
        body["has_video"] = video_path is not None
        body["video_url"] = (
            f"{admin_access_policy.base_path}/agencies/"
            f"{agency_id}/reels/{site_id}/{source_property_id}/video"
            if video_path is not None
            else None
        )
        return JSONResponse(status_code=200, content={"reel": body})

    register_admin_reel_asset_routes(
        router,
        unit_of_work_factory=unit_of_work_factory,
        admin_access_policy=admin_access_policy,
        inspect_reel_use_case=inspect_reel_use_case,
        resolved_workspace_dir=resolved_workspace_dir,
    )

    @router.post(
        "/agencies/{agency_id}/reels/{site_id}/{source_property_id}/approve",
        summary="Approve a reel and regenerate (re-publish) it",
        description=(
            "Two-step action.\n\n"
            "1. The reel is moved to `workflow_state='approved'` / "
            "`publish_status='pending_publish'` so the editor reflects the "
            "new gate immediately.\n"
            "2. A fresh `reel_publish` job is enqueued from the stored "
            "WordPress payload, with `approval_required=False` forced on "
            "the `publish_context`. If the original payload or the agency's "
            "GHL connection is missing, the response stays 200 with "
            "`publish_enqueued=false` so the frontend can render a "
            "consistent state."
        ),
    )
    async def approve_admin_agency_reel(
        agency_id: str,
        site_id: str,
        source_property_id: int,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                result = regenerate_reel_use_case.execute(
                    uow=uow,
                    agency_id=agency_id,
                    site_id=site_id,
                    source_property_id=source_property_id,
                )
        except ResourceNotFoundError as error:
            return _resource_not_found_response(error)
        except ValidationError as error:
            return json_error(
                400,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        except ApplicationError as error:
            return _application_error_response(error)
        body: dict[str, object] = {
            "status": "approved",
            "publish_enqueued": result.publish_enqueued,
            "reel": _serialize_agency_reel(result.reel),
        }
        if result.publish_enqueued:
            body["event_id"] = result.event_id
            body["job_id"] = result.job_id
        else:
            body["reason"] = result.reason
            body["hint"] = result.hint
        return JSONResponse(status_code=200, content=body)

    @router.post(
        "/agencies/{agency_id}/reels/{site_id}/{source_property_id}/reject",
        summary="Reject a reel",
        description=(
            "Sets the reel's pipeline state to `rejected` and the publish "
            "status to `rejected` so it stays out of the publish queue."
        ),
    )
    async def reject_admin_agency_reel(
        agency_id: str,
        site_id: str,
        source_property_id: int,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                item = reject_reel_use_case.execute(
                    uow=uow,
                    agency_id=agency_id,
                    site_id=site_id,
                    source_property_id=source_property_id,
                )
        except ResourceNotFoundError as error:
            return _resource_not_found_response(error)
        except ApplicationError as error:
            return _application_error_response(error)
        return JSONResponse(
            status_code=200,
            content={"status": "rejected", "reel": _serialize_agency_reel(item)},
        )

    return router


__all__ = ["create_admin_reels_router"]
