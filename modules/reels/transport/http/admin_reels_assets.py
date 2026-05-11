"""Asset GET helpers for the admin reels surface.

Covers the four read-only endpoints that stream local files (video,
images list, image stream, manifest) plus the shared serializer/path
helpers used by both this module and the parent router.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import ContextManager

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from apps.api.admin_auth import AdminAccessPolicy, authorize_admin_request
from apps.api.error_handlers import json_error
from apps.api.range_response import build_range_response
from modules.reels.application.use_cases.inspect_reel import InspectReelUseCase
from modules.reels.infrastructure.reel_query import AgencyReelSummary
from shared.db import DatabaseUnitOfWork
from shared.errors import ApplicationError, ResourceNotFoundError

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]

_IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".avif": "image/avif",
}


def _guess_image_mime_type(path: Path) -> str:
    return _IMAGE_MIME_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _serialize_agency_reel(item: AgencyReelSummary) -> dict[str, object]:
    return {
        "site_id": item.external_source_id,
        "source_property_id": item.source_property_id,
        "slug": item.slug,
        "title": item.title,
        "link": item.link,
        "price": item.price,
        "property_status": item.property_status,
        "property_type_label": item.property_type_label,
        "property_area_label": item.property_area_label,
        "property_county_label": item.property_county_label,
        "bedrooms": item.bedrooms,
        "bathrooms": item.bathrooms,
        "featured_image_url": item.featured_image_url,
        "agent_name": item.agent_name,
        "workflow_state": item.workflow_state,
        "publish_status": item.publish_status,
        "render_status": item.render_status,
        "last_published_location_id": item.last_published_provider_external_id,
        "current_revision_id": item.current_revision_id,
        "pipeline_updated_at": item.pipeline_updated_at,
        "pipeline_created_at": item.pipeline_created_at,
        "fetched_at": item.fetched_at,
        "revision_media_path": item.revision_media_path,
        "revision_metadata_path": item.revision_metadata_path,
        "revision_artifact_kind": item.revision_artifact_kind,
        "revision_created_at": item.revision_created_at,
    }


def _resolve_workspace_path(workspace_dir: Path, candidate: str) -> Path | None:
    text = (candidate or "").strip()
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = workspace_dir / path
    if not path.exists() or not path.is_file():
        return None
    return path


def _resource_not_found_response(error: ResourceNotFoundError) -> JSONResponse:
    return json_error(
        404,
        str(error),
        code=error.code,
        hint=error.hint,
        details={"context": error.context} if error.context else None,
    )


def _application_error_response(error: ApplicationError) -> JSONResponse:
    return json_error(
        500,
        str(error),
        code=getattr(error, "code", "ADMIN_REEL_OPERATION_FAILED"),
        hint=getattr(error, "hint", None),
        details=(
            {"context": error.context} if getattr(error, "context", None) else None
        ),
    )


def register_admin_reel_asset_routes(
    router: APIRouter,
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    admin_access_policy: AdminAccessPolicy,
    inspect_reel_use_case: InspectReelUseCase,
    resolved_workspace_dir: Path,
) -> None:
    """Attach the four asset GET routes (video / images / image file / manifest) to ``router``."""

    @router.get(
        "/agencies/{agency_id}/reels/{site_id}/{source_property_id}/video",
        summary="Stream the rendered MP4 for a reel",
        description=(
            "Streams the most recent rendered MP4 for the reel. Honours the "
            "`Range` header so HTML5 `<video>` players can seek and "
            "lazy-load. Returns 404 if no rendered video exists yet."
        ),
        responses={
            200: {"description": "Full MP4 body."},
            206: {"description": "Range chunk (used by HTML5 video for seeking)."},
            404: {"description": "No rendered video for this reel."},
        },
    )
    async def stream_admin_agency_reel_video(
        agency_id: str,
        site_id: str,
        source_property_id: int,
        request: Request,
    ) -> Response:
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
        except ResourceNotFoundError:
            return json_error(
                404,
                "No rendered video is available for this reel.",
                code="ADMIN_REEL_VIDEO_NOT_FOUND",
                details={
                    "agency_id": agency_id,
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                },
            )
        video_path = _resolve_workspace_path(
            resolved_workspace_dir, item.revision_media_path
        )
        if video_path is None:
            return json_error(
                404,
                "No rendered video is available for this reel.",
                code="ADMIN_REEL_VIDEO_NOT_FOUND",
                details={
                    "agency_id": agency_id,
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                },
            )
        return build_range_response(request, video_path)

    @router.get(
        "/agencies/{agency_id}/reels/{site_id}/{source_property_id}/images",
        summary="List the property images that fed the reel",
        description=(
            "Returns every image WordPress shipped for the property, in the "
            "order they were ingested. Each entry includes the original "
            "`image_url`, the local cached path (when downloaded), and a "
            "stable backend URL via `file_url` for locally-cached images."
        ),
    )
    async def list_admin_agency_reel_images(
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
                if uow.tenancy is None or uow.catalog is None:
                    raise RuntimeError("The unit of work is not active.")
                if uow.tenancy.agencies.get_by_id(agency_id) is None:
                    return json_error(
                        404,
                        "The agency does not exist.",
                        code="ADMIN_AGENCY_NOT_FOUND",
                        details={"agency_id": agency_id},
                    )
                images = uow.catalog.images.list_for_property(
                    external_source_id=site_id,
                    source_property_id=source_property_id,
                )
        except ApplicationError as error:
            return _application_error_response(error)
        items = []
        for image in images:
            local_path_text = (image.local_path or "").strip()
            local_available = bool(
                local_path_text
                and _resolve_workspace_path(resolved_workspace_dir, local_path_text)
            )
            items.append(
                {
                    "position": int(image.position),
                    "image_url": image.image_url,
                    "local_path": image.local_path,
                    "has_local_file": local_available,
                    "file_url": (
                        f"{admin_access_policy.base_path}/agencies/"
                        f"{agency_id}/reels/{site_id}/{source_property_id}/images/"
                        f"{int(image.position)}/file"
                        if local_available
                        else None
                    ),
                }
            )
        return JSONResponse(
            status_code=200,
            content={
                "agency_id": agency_id,
                "site_id": site_id,
                "source_property_id": int(source_property_id),
                "items": items,
                "count": len(items),
            },
        )

    @router.get(
        "/agencies/{agency_id}/reels/{site_id}/{source_property_id}"
        "/images/{position}/file",
        summary="Stream one of the property's downloaded image files",
        description=(
            "Serves the locally-cached property image at the given "
            "position. Returns 404 if the image was never downloaded."
        ),
    )
    async def stream_admin_agency_reel_image(
        agency_id: str,
        site_id: str,
        source_property_id: int,
        position: int,
        request: Request,
    ) -> Response:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                if uow.catalog is None:
                    raise RuntimeError("The unit of work is not active.")
                images = uow.catalog.images.list_for_property(
                    external_source_id=site_id,
                    source_property_id=source_property_id,
                )
        except ApplicationError as error:
            return _application_error_response(error)
        target = next(
            (img for img in images if int(img.position) == int(position)),
            None,
        )
        path = (
            _resolve_workspace_path(resolved_workspace_dir, target.local_path or "")
            if target is not None
            else None
        )
        if path is None:
            return json_error(
                404,
                "No locally-cached file for this image position.",
                code="ADMIN_REEL_IMAGE_NOT_FOUND",
                details={
                    "agency_id": agency_id,
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                    "position": position,
                },
            )
        media_type = _guess_image_mime_type(path)

        def iter_file():
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(64 * 1024)
                    if not chunk:
                        break
                    yield chunk

        return StreamingResponse(
            iter_file(),
            media_type=media_type,
            headers={"Cache-Control": "private, max-age=600"},
        )

    @router.get(
        "/agencies/{agency_id}/reels/{site_id}/{source_property_id}/manifest",
        summary="Get the rendered reel's manifest JSON",
        description=(
            "Returns the resolved render manifest for the most recent "
            "revision: scenes, durations, music selection, brand overlay "
            "placement, subtitle layout."
        ),
        responses={
            200: {"description": "Manifest JSON wrapped in `{ manifest: … }`."},
            404: {"description": "No manifest is available for this reel."},
        },
    )
    async def get_admin_agency_reel_manifest(
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
        manifest_path = _resolve_workspace_path(
            resolved_workspace_dir, item.revision_metadata_path
        )
        if manifest_path is None:
            return json_error(
                404,
                "No manifest available for this reel.",
                code="ADMIN_REEL_MANIFEST_NOT_FOUND",
                details={
                    "agency_id": agency_id,
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                },
            )
        try:
            manifest_text = manifest_path.read_text(encoding="utf-8")
            manifest = json.loads(manifest_text)
        except (OSError, json.JSONDecodeError) as error:
            return json_error(
                500,
                "Failed to read manifest.",
                code="ADMIN_REEL_MANIFEST_READ_FAILED",
                details={"error": str(error)},
            )
        manifest_path_relative = (
            str(manifest_path.relative_to(resolved_workspace_dir))
            if manifest_path.is_relative_to(resolved_workspace_dir)
            else str(manifest_path)
        )
        return JSONResponse(
            status_code=200,
            content={
                "agency_id": agency_id,
                "site_id": site_id,
                "source_property_id": int(source_property_id),
                "manifest_path": manifest_path_relative,
                "manifest": manifest,
            },
        )


__all__ = [
    "_application_error_response",
    "_guess_image_mime_type",
    "_resolve_workspace_path",
    "_resource_not_found_response",
    "_serialize_agency_reel",
    "register_admin_reel_asset_routes",
]
