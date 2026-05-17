"""FastAPI router for the agency intro-video upload endpoints (feature 34).

Exposes three endpoints under ``/v1/admin/agencies/{agency_id}/intro``:

* ``POST .../upload`` — multipart upload (``file`` field, MP4/MOV).
  Validates MIME, size (<=50MB) and duration (1..10s via ffprobe).
* ``GET  .../file``    — stream the binary back to the admin UI.
* ``DELETE ...``       — clear the metadata and remove the on-disk blob.

Symmetric to :mod:`outro_router` from feature 33. The multipart parsing
reuses the stdlib ``email`` strategy from ``brand_logo_router.py`` and
``music_upload_router.py`` so we don't add the ``python-multipart``
dependency. Authorization goes through
:func:`apps.api.admin_auth.authorize_admin_request`, keeping the same
agency-scoped JWT contract as the rest of the admin surface.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from typing import ContextManager

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from apps.api.admin_auth import AdminAccessPolicy, authorize_admin_request
from apps.api.error_handlers import json_error
from modules.configuration.application.use_cases.delete_intro_video import (
    DeleteIntroVideoInput,
    DeleteIntroVideoUseCase,
)
from modules.configuration.application.use_cases.read_intro_asset import (
    ReadIntroAssetUseCase,
)
from modules.configuration.application.use_cases.upload_intro_video import (
    INTRO_MAX_UPLOAD_BYTES,
    UploadIntroVideoInput,
    UploadIntroVideoUseCase,
)
from modules.configuration.domain import IntroOutroAsset
from shared.db import DatabaseUnitOfWork
from shared.errors import (
    ApplicationError,
    ResourceNotFoundError,
    ValidationError,
)
from shared.storage.site_layout import (
    resolve_agency_intro_outro_local_path,
)

logger = logging.getLogger(__name__)

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]

_MULTIPART_BOUNDARY_RE = re.compile(r'boundary\s*=\s*"?([^";]+)"?', re.IGNORECASE)
_MEDIA_TYPE_BY_EXTENSION = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
}


@dataclass(frozen=True, slots=True)
class _UploadedField:
    filename: str
    content_type: str
    body: bytes


class _MultipartParseError(Exception):
    """Raised when the request body cannot be parsed as multipart/form-data."""


def _extract_boundary(content_type: str) -> str | None:
    match = _MULTIPART_BOUNDARY_RE.search(content_type or "")
    if match is None:
        return None
    return match.group(1).strip()


def _parse_header_params(header_value: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for fragment in (header_value or "").split(";"):
        chunk = fragment.strip()
        if "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        params[key.strip().lower()] = value.strip().strip('"')
    return params


def _extract_file_field(
    body: bytes, content_type_header: str
) -> _UploadedField | None:
    boundary = _extract_boundary(content_type_header)
    if not boundary:
        raise _MultipartParseError(
            "Missing multipart boundary in the Content-Type header."
        )
    header_bytes = (
        f"Content-Type: multipart/form-data; boundary={boundary}\r\n\r\n"
    ).encode("utf-8")
    parser = BytesParser(_class=EmailMessage, policy=policy.default)
    message = parser.parsebytes(header_bytes + body)
    if not message.is_multipart():
        raise _MultipartParseError("Request body is not multipart/form-data.")

    for part in message.iter_parts():
        if not isinstance(part, EmailMessage):
            continue
        params = _parse_header_params(part.get("content-disposition", ""))
        if params.get("name") != "file":
            continue
        filename = params.get("filename") or ""
        part_content_type = (part.get_content_type() or "").lower()
        raw_body = part.get_payload(decode=True) or b""
        return _UploadedField(
            filename=filename,
            content_type=part_content_type,
            body=raw_body,
        )
    return None


def create_intro_router(
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    admin_access_policy: AdminAccessPolicy,
    workspace_dir: Path,
    upload_intro_video: UploadIntroVideoUseCase | None = None,
    read_intro_asset: ReadIntroAssetUseCase | None = None,
    delete_intro_video: DeleteIntroVideoUseCase | None = None,
    max_upload_bytes: int = INTRO_MAX_UPLOAD_BYTES,
) -> APIRouter:
    router = APIRouter(
        prefix=admin_access_policy.base_path,
        tags=["Admin · Intro"],
    )
    resolved_workspace = Path(workspace_dir).expanduser().resolve()
    upload_use_case = upload_intro_video or UploadIntroVideoUseCase(
        workspace_dir=resolved_workspace,
        max_upload_bytes=max_upload_bytes,
    )
    read_use_case = read_intro_asset or ReadIntroAssetUseCase()
    delete_use_case = delete_intro_video or DeleteIntroVideoUseCase(
        workspace_dir=resolved_workspace,
    )

    @router.post(
        "/agencies/{agency_id}/intro/upload",
        summary="Upload the agency's intro video (multipart, MP4/MOV, <=50MB, 1-10s)",
        description=(
            "Accepts a multipart `file` field (MP4 or MOV) and stores it "
            "under the agency's intro folder. Validates size (<=50MB) and "
            "duration (1..10s via ffprobe). Returns the asset metadata "
            "(`intro_object_key`, `intro_duration_seconds`, `intro_source = "
            "\"uploaded\"`). Errors: 422 INTRO_INVALID_MIME, 413 "
            "INTRO_FILE_TOO_LARGE, 422 INTRO_INVALID_DURATION, 404 "
            "ADMIN_AGENCY_NOT_FOUND."
        ),
    )
    async def upload_admin_agency_intro(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error

        content_type_header = request.headers.get("content-type", "")
        if not content_type_header.lower().startswith("multipart/form-data"):
            return json_error(
                415,
                "Intro upload requires multipart/form-data.",
                code="INTRO_UPLOAD_UNSUPPORTED_TYPE",
                details={"received_content_type": content_type_header},
            )

        body = await request.body()
        if len(body) > max_upload_bytes:
            return json_error(
                413,
                "Intro upload exceeds the 50 MB size limit.",
                code="INTRO_FILE_TOO_LARGE",
                details={
                    "received_bytes": len(body),
                    "max_bytes": max_upload_bytes,
                },
            )

        try:
            field = _extract_file_field(body, content_type_header)
        except _MultipartParseError as error:
            return json_error(
                422,
                f"Could not parse multipart body: {error}",
                code="INTRO_UPLOAD_MALFORMED",
            )
        if field is None:
            return json_error(
                422,
                "The 'file' multipart field is required.",
                code="INTRO_UPLOAD_MISSING_FIELD",
            )

        try:
            with unit_of_work_factory() as uow:
                asset = upload_use_case.execute(
                    uow=uow,
                    data=UploadIntroVideoInput(
                        agency_id=agency_id,
                        content_type=field.content_type,
                        body=field.body,
                    ),
                )
        except ValidationError as error:
            status_code = 413 if error.code == "INTRO_FILE_TOO_LARGE" else 422
            return json_error(
                status_code,
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
        except ApplicationError as error:  # pragma: no cover — defensive
            logger.exception(
                "Intro upload failed for agency=%s", agency_id,
            )
            return json_error(
                500,
                str(error),
                code=getattr(error, "code", "INTRO_UPLOAD_FAILED"),
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )

        return JSONResponse(
            status_code=200,
            content=_serialize_asset(asset),
        )

    @router.get(
        "/agencies/{agency_id}/intro/file",
        summary="Stream the agency's previously uploaded intro video",
        description=(
            "Serves the bytes of the intro registered for the agency. "
            "Returns 404 if no intro is configured or the on-disk blob has "
            "been removed."
        ),
    )
    async def stream_admin_agency_intro(
        agency_id: str,
        request: Request,
    ) -> Response:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                asset = read_use_case.execute(uow=uow, agency_id=agency_id)
        except ResourceNotFoundError as error:
            return json_error(
                404,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )

        if asset is None or asset.source != "uploaded" or not asset.object_key:
            return json_error(
                404,
                "Intro video not configured.",
                code="INTRO_FILE_NOT_FOUND",
                details={"agency_id": agency_id},
            )

        path = resolve_agency_intro_outro_local_path(
            workspace_dir=resolved_workspace,
            object_key=asset.object_key,
        )
        if path is None:
            return json_error(
                404,
                "Intro video binary not found on disk.",
                code="INTRO_FILE_NOT_FOUND",
                details={"agency_id": agency_id},
            )

        suffix = path.suffix.lower()
        media_type = _MEDIA_TYPE_BY_EXTENSION.get(suffix, "application/octet-stream")

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
            headers={
                "Content-Disposition": "inline",
                "Cache-Control": "private, max-age=600",
            },
        )

    @router.delete(
        "/agencies/{agency_id}/intro",
        summary="Delete the agency's intro video",
        description=(
            "Resets the intro metadata to ``source='none'`` (object_key "
            "cleared) and removes the on-disk blob. Idempotent — a DELETE "
            "without a prior upload returns the same shape."
        ),
    )
    async def delete_admin_agency_intro(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                asset = delete_use_case.execute(
                    uow=uow,
                    data=DeleteIntroVideoInput(agency_id=agency_id),
                )
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
            content=_serialize_asset(asset),
        )

    return router


def _serialize_asset(asset: IntroOutroAsset) -> dict[str, object]:
    object_key = asset.object_key if asset.source == "uploaded" else ""
    duration_seconds: int | None = (
        int(asset.duration_seconds)
        if asset.source == "uploaded" and asset.duration_seconds > 0
        else None
    )
    return {
        "intro_object_key": object_key or None,
        "intro_duration_seconds": duration_seconds,
        "intro_source": asset.source,
    }


__all__ = ["create_intro_router"]
