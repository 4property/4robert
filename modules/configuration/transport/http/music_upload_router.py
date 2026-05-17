"""FastAPI router for the agency music-upload endpoints.

`POST /v1/admin/agencies/{agency_id}/music/upload` accepts a multipart
upload (``file`` + ``display_name`` + ``is_default``), persists the
binary under the agency's ``_agency_music/`` workspace folder, probes
its duration via ``ffprobe`` and registers the row in
``agency_music_tracks``. The companion
``GET /v1/admin/agencies/{agency_id}/music/{music_id}/file/{filename}``
streams the blob back so the admin UI can preview it.

This router is intentionally separate from ``music_router.py`` because
multipart parsing has a different shape than the JSON CRUD endpoints —
the parser is borrowed from ``brand_logo_router.py`` (stdlib ``email``
parser, no ``python-multipart`` dependency).
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
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
from modules.configuration.application.use_cases.inspect_music_track import (
    InspectMusicTrackUseCase,
)
from modules.configuration.application.use_cases.upload_music_track import (
    UploadMusicTrackInput,
    UploadMusicTrackUseCase,
)
from modules.configuration.domain import MusicTrack
from shared.db import DatabaseUnitOfWork
from shared.errors import (
    ApplicationError,
    ResourceNotFoundError,
    ValidationError,
)
from shared.storage.site_layout import (
    resolve_agency_music_local_path,
    safe_site_dirname,
)

logger = logging.getLogger(__name__)

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]

# 20 MB cap — accommodates the ~9 MB MP3s already shipped in
# ``assets/music`` with headroom for higher-bitrate uploads.
MUSIC_UPLOAD_MAX_BYTES = 20 * 1024 * 1024
DISPLAY_NAME_MAX_LENGTH = 200

_ALLOWED_CONTENT_TYPES = frozenset(
    {
        "audio/mpeg",
        "audio/mp4",
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
    }
)
_SUFFIX_BY_CONTENT_TYPE = {
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
}

_MULTIPART_BOUNDARY_RE = re.compile(r'boundary\s*=\s*"?([^";]+)"?', re.IGNORECASE)
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

# Magic-byte heuristics. The check is intentionally tolerant: real-world
# MP3 files frequently start with ``ID3`` (v2 tag) or a raw MPEG frame
# header (``0xFF 0xFB/0xF3/0xF2`` etc.); M4A/MP4 starts with an ``ftyp``
# atom at offset 4; WAV starts with ``RIFF...WAVE``.
def _looks_like_mp3(head: bytes) -> bool:
    if not head:
        return False
    if head.startswith(b"ID3"):
        return True
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        return True
    return False


def _looks_like_m4a(head: bytes) -> bool:
    return len(head) >= 12 and head[4:8] == b"ftyp"


def _looks_like_wav(head: bytes) -> bool:
    return (
        len(head) >= 12
        and head[0:4] == b"RIFF"
        and head[8:12] == b"WAVE"
    )


def _magic_bytes_match(content_type: str, head: bytes) -> bool:
    if content_type == "audio/mpeg":
        return _looks_like_mp3(head)
    if content_type == "audio/mp4":
        return _looks_like_m4a(head)
    if content_type in {"audio/wav", "audio/x-wav", "audio/wave"}:
        return _looks_like_wav(head)
    return False


@dataclass(frozen=True, slots=True)
class _UploadFields:
    filename: str
    content_type: str
    body: bytes
    display_name: str
    is_default: bool


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


def _decode_text_part(part: EmailMessage) -> str:
    raw = part.get_payload(decode=True)
    if raw is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return raw.decode(charset, errors="strict")
    except (UnicodeDecodeError, LookupError):
        return raw.decode("utf-8", errors="replace")


def _parse_is_default(raw: str) -> bool:
    cleaned = (raw or "").strip().lower()
    if cleaned in {"1", "true", "yes", "on"}:
        return True
    if cleaned in {"", "0", "false", "no", "off"}:
        return False
    raise _MultipartParseError(
        f"Unsupported value for 'is_default': {raw!r}"
    )


def _extract_upload_fields(
    body: bytes, content_type_header: str
) -> _UploadFields:
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

    file_part: EmailMessage | None = None
    display_name = ""
    is_default_raw: str | None = None
    seen_display_name = False
    for part in message.iter_parts():
        if not isinstance(part, EmailMessage):
            continue
        params = _parse_header_params(part.get("content-disposition", ""))
        name = params.get("name")
        if name == "file" and file_part is None:
            file_part = part
        elif name == "display_name":
            seen_display_name = True
            display_name = _decode_text_part(part)
        elif name == "is_default":
            is_default_raw = _decode_text_part(part)

    if file_part is None:
        raise _MultipartParseError(
            "The 'file' multipart field is required."
        )
    if not seen_display_name:
        raise _MultipartParseError(
            "The 'display_name' multipart field is required."
        )

    file_params = _parse_header_params(file_part.get("content-disposition", ""))
    filename = file_params.get("filename") or ""
    raw_body = file_part.get_payload(decode=True) or b""
    file_content_type = (file_part.get_content_type() or "").strip().lower()

    is_default = _parse_is_default(is_default_raw or "false")
    return _UploadFields(
        filename=filename,
        content_type=file_content_type,
        body=raw_body,
        display_name=display_name,
        is_default=is_default,
    )


def _normalize_filename(raw: str, content_type: str, body: bytes) -> str:
    """Build a deterministic on-disk filename.

    Strips path separators / unicode oddities from the upload filename
    and falls back to ``track-<sha1>.<ext>`` when nothing usable
    survives. The extension is derived from the content-type so a
    spoofed ``audio.exe`` cannot smuggle ``.exe`` into the storage path.
    """
    suffix = _SUFFIX_BY_CONTENT_TYPE.get(content_type, ".bin")
    normalized = unicodedata.normalize("NFKD", raw or "")
    stem = Path(normalized).stem
    cleaned = _SAFE_FILENAME_RE.sub("-", stem).strip("-._") if stem else ""
    if not cleaned:
        digest = hashlib.sha1(body).hexdigest()[:12]
        cleaned = f"track-{digest}"
    # Bound the stem so a path-traversal-style 500-char input cannot
    # blow up the on-disk inode name.
    cleaned = cleaned[:96]
    return f"{cleaned}{suffix}"


def create_music_upload_router(
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    admin_access_policy: AdminAccessPolicy,
    workspace_dir: Path,
    upload_music_track: UploadMusicTrackUseCase | None = None,
    inspect_music_track: InspectMusicTrackUseCase | None = None,
    max_upload_bytes: int = MUSIC_UPLOAD_MAX_BYTES,
) -> APIRouter:
    router = APIRouter(
        prefix=admin_access_policy.base_path,
        tags=["Admin · Music"],
    )
    resolved_workspace = Path(workspace_dir).expanduser().resolve()
    upload_use_case = upload_music_track or UploadMusicTrackUseCase(
        workspace_dir=resolved_workspace,
    )
    inspect_use_case = inspect_music_track or InspectMusicTrackUseCase()

    @router.post(
        "/agencies/{agency_id}/music/upload",
        summary="Upload a new music track (multipart, <=20MB)",
        description=(
            "Accepts a multipart body with `file` (audio binary), "
            "`display_name` (label, 1..200 chars) and `is_default` "
            "(`true`/`false`). Supported MIME types: audio/mpeg, "
            "audio/mp4, audio/wav. The backend persists the binary "
            "under the agency's music folder, probes the duration via "
            "ffprobe and registers a row in `agency_music_tracks`. "
            "Returns 201 with the saved `music_track`. Errors: 400 "
            "MUSIC_TRACK_AUDIO_INVALID (bad MIME / ffprobe failure / "
            "duration > 10min), 413 if the payload is over 20 MB, 422 "
            "if `display_name` is missing or blank, 404 if the agency "
            "is unknown."
        ),
    )
    async def upload_admin_agency_music_track(
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
                "Music upload requires multipart/form-data.",
                code="MUSIC_TRACK_UPLOAD_UNSUPPORTED_TYPE",
                details={"received_content_type": content_type_header},
            )

        body = await request.body()
        # 413 must trigger before we hand the body to the email parser
        # so a multi-GB payload never reaches the stdlib parser.
        if len(body) > max_upload_bytes:
            return json_error(
                413,
                "Music upload exceeds the 20 MB size limit.",
                code="MUSIC_TRACK_UPLOAD_TOO_LARGE",
                details={
                    "received_bytes": len(body),
                    "max_bytes": max_upload_bytes,
                },
            )

        try:
            fields = _extract_upload_fields(body, content_type_header)
        except _MultipartParseError as error:
            return json_error(
                422,
                f"Could not parse multipart body: {error}",
                code="MUSIC_TRACK_UPLOAD_MALFORMED",
            )

        display_name = (fields.display_name or "").strip()
        if not display_name:
            return json_error(
                422,
                "The 'display_name' multipart field is required.",
                code="MUSIC_TRACK_DISPLAY_NAME_REQUIRED",
            )
        if len(display_name) > DISPLAY_NAME_MAX_LENGTH:
            return json_error(
                422,
                (
                    "The 'display_name' field is too long "
                    f"(max {DISPLAY_NAME_MAX_LENGTH} characters)."
                ),
                code="MUSIC_TRACK_DISPLAY_NAME_TOO_LONG",
                details={"received_length": len(display_name)},
            )

        content_type = (fields.content_type or "").strip().lower()
        if content_type not in _ALLOWED_CONTENT_TYPES:
            return json_error(
                400,
                "Unsupported audio content-type. Use mp3, m4a or wav.",
                code="MUSIC_TRACK_AUDIO_INVALID",
                hint="Re-encode the audio as mp3/m4a/wav and try again.",
                details={
                    "received_content_type": fields.content_type or "",
                    "allowed_content_types": sorted(_ALLOWED_CONTENT_TYPES),
                },
            )

        if not fields.body:
            return json_error(
                422,
                "Music upload payload is empty.",
                code="MUSIC_TRACK_UPLOAD_EMPTY",
            )
        if len(fields.body) > max_upload_bytes:
            # Defence in depth: the outer 413 already handles this, but
            # an attacker could keep the envelope small while inflating
            # the inner part.
            return json_error(
                413,
                "Music upload exceeds the 20 MB size limit.",
                code="MUSIC_TRACK_UPLOAD_TOO_LARGE",
                details={
                    "received_bytes": len(fields.body),
                    "max_bytes": max_upload_bytes,
                },
            )

        head = fields.body[:32]
        if not _magic_bytes_match(content_type, head):
            return json_error(
                400,
                "Audio magic bytes do not match the declared content-type.",
                code="MUSIC_TRACK_AUDIO_INVALID",
                hint=(
                    "The first bytes of the file do not look like the "
                    "declared MIME type. Re-export the audio and retry."
                ),
                details={
                    "received_content_type": content_type,
                    "magic_prefix": head[:8].hex(),
                },
            )

        filename = _normalize_filename(fields.filename, content_type, fields.body)

        try:
            with unit_of_work_factory() as uow:
                track = upload_use_case.execute(
                    uow=uow,
                    data=UploadMusicTrackInput(
                        agency_id=agency_id,
                        filename=filename,
                        body=fields.body,
                        display_name=display_name,
                        is_default=fields.is_default,
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
            logger.exception(
                "Music track upload failed for agency=%s filename=%s",
                agency_id,
                filename,
            )
            return json_error(
                500,
                str(error),
                code=getattr(error, "code", "MUSIC_TRACK_SAVE_FAILED"),
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )

        return JSONResponse(
            status_code=201,
            content={
                "status": "created",
                "agency_id": agency_id,
                "music_track": _serialize_track(track),
            },
        )

    @router.get(
        "/agencies/{agency_id}/music/{music_id}/file/{filename}",
        summary="Stream a previously uploaded music track binary",
        description=(
            "Serves the audio binary registered for `music_id`. The "
            "filename in the URL must match the trailing segment of the "
            "track's `object_key` (the upload endpoint returns that "
            "key). The path is scope-checked against the agency JWT: a "
            "request that targets another agency's track responds 404. "
            "Returns 404 if the track does not exist or the on-disk "
            "binary has been removed."
        ),
    )
    async def stream_admin_agency_music_track(
        agency_id: str,
        music_id: str,
        filename: str,
        request: Request,
    ) -> Response:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error

        if not filename or filename in {".", ".."} or "/" in filename or "\\" in filename:
            return json_error(
                404,
                "Music track file not found.",
                code="MUSIC_TRACK_FILE_NOT_FOUND",
                details={"agency_id": agency_id, "music_id": music_id, "filename": filename},
            )

        try:
            with unit_of_work_factory() as uow:
                track = inspect_use_case.execute(
                    uow=uow,
                    agency_id=agency_id,
                    music_id=music_id,
                )
        except ResourceNotFoundError as error:
            return json_error(
                404,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )

        # Re-derive the expected filename from the stored object_key so
        # an attacker cannot probe arbitrary files in the agency folder
        # — only the canonical name resolves.
        expected_filename = Path(track.object_key).name
        if filename != expected_filename:
            return json_error(
                404,
                "Music track file not found.",
                code="MUSIC_TRACK_FILE_NOT_FOUND",
                details={
                    "agency_id": agency_id,
                    "music_id": music_id,
                    "filename": filename,
                },
            )

        safe_agency = safe_site_dirname(agency_id)
        object_key = f"agencies/{safe_agency}/music/{filename}"
        path = resolve_agency_music_local_path(
            workspace_dir=resolved_workspace,
            object_key=object_key,
        )
        if path is None:
            return json_error(
                404,
                "Music track file not found.",
                code="MUSIC_TRACK_FILE_NOT_FOUND",
                details={"agency_id": agency_id, "music_id": music_id, "filename": filename},
            )

        suffix = path.suffix.lower()
        media_type = {
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".wav": "audio/wav",
        }.get(suffix, "application/octet-stream")

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


def _serialize_track(track: MusicTrack) -> dict[str, object]:
    return {
        "music_id": track.music_id,
        "agency_id": track.agency_id,
        "display_name": track.display_name,
        "object_key": track.object_key,
        "duration_seconds": track.duration_seconds,
        "is_default": track.is_default,
        "created_at": track.created_at,
    }


__all__ = [
    "DISPLAY_NAME_MAX_LENGTH",
    "MUSIC_UPLOAD_MAX_BYTES",
    "create_music_upload_router",
]
