"""FastAPI router for the agency brand-logo upload endpoint.

`/v1/admin/agencies/{agency_id}/brand/logo` — accept a multipart upload
(JPG/PNG, <=5MB) and persist the binary under the agency's
``_agency_branding/`` workspace folder. Returns the opaque
``object_key`` together with an admin URL that streams the file back.

The endpoint is intentionally filesystem-only today: the storage helper
:func:`shared.storage.site_layout.resolve_agency_branding_destination`
returns an ``(object_key, local_path)`` tuple so a future S3 backend can
be plugged in without changing the HTTP contract.

The companion ``GET .../brand/logo/file/{filename}`` route serves the
binary back to the admin UI (parity with ``stream_admin_agency_reel_image``).
The agency-scoped JWT path-prefix check in
:func:`apps.api.admin_auth.authorize_admin_request` already isolates one
agency's logos from another's.

To remove an uploaded logo, the admin sends ``logo_object_key: ""`` to
``PUT /agencies/{id}/brand`` — string-empty is the "no logo" sentinel
matching the ``Text NOT NULL DEFAULT ''`` column. ``null`` is NOT a
delete operator: the brand PUT treats ``null`` as "do not touch".

Multipart parsing note
----------------------
FastAPI's ``UploadFile`` machinery requires the third-party
``python-multipart`` package, which is not part of the project's
``requirements.txt``. To keep the dependency surface intact this router
reads the raw request body and parses ``multipart/form-data`` with the
stdlib ``email`` module. The endpoint only accepts a single ``file``
field, so a hand-rolled split is sufficient and predictable.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage
from email.parser import BytesParser
from email import policy
from pathlib import Path
from typing import ContextManager

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from apps.api.admin_auth import AdminAccessPolicy, authorize_admin_request
from apps.api.error_handlers import json_error
from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
)
from shared.db import DatabaseUnitOfWork
from shared.errors import ResourceNotFoundError
from shared.storage.site_layout import (
    resolve_agency_branding_destination,
    resolve_agency_branding_local_path,
    safe_site_dirname,
)

logger = logging.getLogger(__name__)

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]

# Inline constants — the codebase has no existing convention for
# admin-upload limits and ``WEBHOOK_MAX_PAYLOAD_BYTES`` is webhook-only
# (see the spike for feature 10).
BRAND_LOGO_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
_ALLOWED_CONTENT_TYPES = frozenset({"image/jpeg", "image/png"})
_ALLOWED_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})
_SUFFIX_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
}
_MULTIPART_BOUNDARY_RE = re.compile(r'boundary\s*=\s*"?([^";]+)"?', re.IGNORECASE)


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


def _extract_file_field(body: bytes, content_type_header: str) -> _UploadedField | None:
    """Parse a ``multipart/form-data`` body and return the ``file`` part.

    The endpoint only declares one field (``file``). If the body contains
    multiple parts the first one named ``file`` is returned; any other
    parts are ignored. Returns ``None`` when no ``file`` part is present
    and raises :class:`_MultipartParseError` on malformed bodies.
    """
    boundary = _extract_boundary(content_type_header)
    if not boundary:
        raise _MultipartParseError(
            "Missing multipart boundary in the Content-Type header."
        )

    # Synthesise an RFC-822 wrapper so the stdlib ``email`` parser can
    # split the parts. ``EmailMessage`` understands ``Content-Disposition``
    # and reports the filename + content-type for each part.
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
        content_disposition = part.get("content-disposition", "")
        params = _parse_header_params(content_disposition)
        if params.get("name") != "file":
            continue
        filename = params.get("filename") or ""
        part_content_type = (part.get_content_type() or "").lower()
        # ``get_payload(decode=True)`` reverses the transfer-encoding
        # applied to the part (typically identity for binary uploads).
        raw_body = part.get_payload(decode=True)
        if raw_body is None:
            raw_body = b""
        return _UploadedField(
            filename=filename,
            content_type=part_content_type,
            body=raw_body,
        )
    return None


def _parse_header_params(header_value: str) -> dict[str, str]:
    """Parse ``Content-Disposition`` parameters into a dict.

    Strips surrounding quotes from values. Quietly tolerates malformed
    fragments — the caller verifies the required keys downstream.
    """
    params: dict[str, str] = {}
    for fragment in (header_value or "").split(";"):
        chunk = fragment.strip()
        if "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        params[key.strip().lower()] = value.strip().strip('"')
    return params


def create_brand_logo_router(
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    admin_access_policy: AdminAccessPolicy,
    workspace_dir: Path,
    max_upload_bytes: int = BRAND_LOGO_MAX_UPLOAD_BYTES,
) -> APIRouter:
    router = APIRouter(
        prefix=admin_access_policy.base_path,
        tags=["Admin · Brand"],
    )
    resolved_workspace = Path(workspace_dir).expanduser().resolve()

    @router.post(
        "/agencies/{agency_id}/brand/logo",
        summary="Upload the agency's branding logo (JPG/PNG, <=5MB)",
        description=(
            "Accepts a multipart `file` field with content-type "
            "`image/jpeg` or `image/png` and stores the binary under the "
            "workspace's agency-branding folder. The response carries "
            "`object_key` (stable opaque identifier the admin sends back "
            "via PUT /agencies/{id}/brand to attach the logo) and `url` "
            "(an admin endpoint that streams the binary back for "
            "previews). Returns 415 if the content-type is not "
            "JPG/PNG, 422 if the filename extension and content-type do "
            "not agree, and 413 if the payload exceeds 5 MB."
        ),
    )
    async def upload_admin_agency_brand_logo(
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
                "Brand logo upload requires multipart/form-data.",
                code="BRAND_LOGO_UPLOAD_UNSUPPORTED_TYPE",
                details={"received_content_type": content_type_header},
            )

        body = await request.body()
        # 413 must trigger before parsing so a multi-GB body never
        # reaches the email parser (still buffered in memory by FastAPI,
        # but bounded here).
        if len(body) > max_upload_bytes:
            return json_error(
                413,
                "Logo upload exceeds the 5 MB size limit.",
                code="BRAND_LOGO_UPLOAD_TOO_LARGE",
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
                code="BRAND_LOGO_UPLOAD_MALFORMED",
            )
        if field is None:
            return json_error(
                422,
                "The 'file' multipart field is required.",
                code="BRAND_LOGO_UPLOAD_MISSING_FIELD",
            )

        content_type = (field.content_type or "").strip().lower()
        if content_type not in _ALLOWED_CONTENT_TYPES:
            return json_error(
                415,
                "Unsupported logo content-type. Use image/jpeg or image/png.",
                code="BRAND_LOGO_UPLOAD_UNSUPPORTED_TYPE",
                details={
                    "received_content_type": field.content_type or "",
                    "allowed_content_types": sorted(_ALLOWED_CONTENT_TYPES),
                },
            )

        raw_filename = (field.filename or "").strip()
        suffix = Path(raw_filename).suffix.lower() if raw_filename else ""
        if suffix not in _ALLOWED_SUFFIXES:
            return json_error(
                422,
                "Unsupported logo file extension. Use .jpg, .jpeg or .png.",
                code="BRAND_LOGO_UPLOAD_UNSUPPORTED_EXTENSION",
                details={
                    "received_filename": raw_filename,
                    "allowed_extensions": sorted(_ALLOWED_SUFFIXES),
                },
            )

        # Cross-check: a client claiming image/png cannot upload a
        # .jpg, and vice versa. This blocks trivial mime-spoofing where
        # a renamed binary slips through the content-type guard.
        expected_suffix_group = (
            {".jpg", ".jpeg"} if content_type == "image/jpeg" else {".png"}
        )
        if suffix not in expected_suffix_group:
            return json_error(
                422,
                "Logo content-type does not match the file extension.",
                code="BRAND_LOGO_UPLOAD_TYPE_EXTENSION_MISMATCH",
                details={
                    "received_content_type": content_type,
                    "received_extension": suffix,
                },
            )

        if not field.body:
            return json_error(
                422,
                "Logo upload payload is empty.",
                code="BRAND_LOGO_UPLOAD_EMPTY",
            )
        if len(field.body) > max_upload_bytes:
            # Defence in depth: the outer 413 already catches this, but
            # an attacker could shrink the surrounding multipart envelope
            # while still shipping a large file part.
            return json_error(
                413,
                "Logo upload exceeds the 5 MB size limit.",
                code="BRAND_LOGO_UPLOAD_TOO_LARGE",
                details={
                    "received_bytes": len(field.body),
                    "max_bytes": max_upload_bytes,
                },
            )

        try:
            with unit_of_work_factory() as uow:
                ensure_agency_exists(uow, agency_id)
        except ResourceNotFoundError as error:
            return json_error(
                404,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )

        digest = hashlib.sha1(field.body).hexdigest()[:12]
        normalized_suffix = _SUFFIX_BY_CONTENT_TYPE[content_type]
        filename = f"logo-{digest}{normalized_suffix}"
        object_key, destination = resolve_agency_branding_destination(
            workspace_dir=resolved_workspace,
            agency_id=agency_id,
            filename=filename,
        )
        try:
            destination.write_bytes(field.body)
        except OSError as error:
            logger.exception(
                "Failed to persist agency logo upload for agency=%s file=%s",
                agency_id,
                destination,
            )
            return json_error(
                500,
                "Could not persist the agency logo upload.",
                code="BRAND_LOGO_UPLOAD_WRITE_FAILED",
                details={"error": str(error)},
            )

        file_url = (
            f"{admin_access_policy.base_path}"
            f"/agencies/{agency_id}/brand/logo/file/{filename}"
        )
        return JSONResponse(
            status_code=200,
            content={
                "object_key": object_key,
                "url": file_url,
            },
        )

    @router.get(
        "/agencies/{agency_id}/brand/logo/file/{filename}",
        summary="Stream a previously uploaded agency brand logo",
        description=(
            "Serves the binary previously uploaded via "
            "`POST /agencies/{id}/brand/logo`. The filename is the trailing "
            "segment of the persisted `object_key` (e.g. "
            "`logo-abcdef012345.png`). Returns 404 if the file does not "
            "exist or has been removed from the workspace."
        ),
    )
    async def stream_admin_agency_brand_logo(
        agency_id: str,
        filename: str,
        request: Request,
    ) -> Response:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error

        # Block traversal/special segments before touching the workspace.
        if not filename or filename in {".", ".."} or "/" in filename:
            return json_error(
                404,
                "Logo file not found.",
                code="BRAND_LOGO_FILE_NOT_FOUND",
                details={"agency_id": agency_id, "filename": filename},
            )

        # ``resolve_agency_branding_destination`` normalises agency_id via
        # ``safe_site_dirname`` when writing the file — apply the same
        # normalisation here so the on-disk layout matches the URL.
        safe_agency = safe_site_dirname(agency_id)
        object_key = f"agencies/{safe_agency}/{filename}"
        path = resolve_agency_branding_local_path(
            workspace_dir=resolved_workspace,
            object_key=object_key,
        )
        if path is None:
            return json_error(
                404,
                "Logo file not found.",
                code="BRAND_LOGO_FILE_NOT_FOUND",
                details={"agency_id": agency_id, "filename": filename},
            )

        suffix = path.suffix.lower()
        media_type = "image/png" if suffix == ".png" else "image/jpeg"

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

    return router


__all__ = [
    "BRAND_LOGO_MAX_UPLOAD_BYTES",
    "create_brand_logo_router",
]
