"""Upload an outro video binary, probe its duration and persist the row.

This use case is the application orchestration behind
``POST /v1/admin/agencies/{agency_id}/outro/upload`` (feature 33). The
HTTP layer parses the multipart envelope and enforces the gross size
cap (the 50MB limit is duplicated here defensively).

Steps:

1. Validate ``content_type`` against the allowed MIME set
   (``video/mp4`` / ``video/quicktime``).
2. Validate ``len(body) <= max_upload_bytes`` (50MB).
3. Write the binary to disk atomically via
   :func:`shared.storage.site_layout.resolve_agency_intro_outro_destination`.
4. Probe duration with ``ffprobe``; reject if outside ``[1, 10]``
   seconds.
5. Persist the row in ``agency_intro_outro_assets`` via the UoW. Drop
   any prior blob from disk after a successful overwrite so the
   workspace never accumulates orphans.

The HTTP-facing error codes (``INVALID_MIME``, ``FILE_TOO_LARGE``,
``INVALID_DURATION``) are surfaced as ``ValidationError(code=...)`` so
the router can translate them to 422 / 413 deterministically.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess  # nosec B404 — we shell out to ffprobe with a fixed argv
import tempfile
from dataclasses import dataclass
from pathlib import Path

from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
)
from modules.configuration.domain import IntroOutroAsset
from shared.db import DatabaseUnitOfWork
from shared.errors import ValidationError
from shared.storage.site_layout import (
    resolve_agency_intro_outro_destination,
    resolve_agency_intro_outro_local_path,
    safe_site_dirname,
)

logger = logging.getLogger(__name__)

OUTRO_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
OUTRO_MIN_DURATION_SECONDS = 1
OUTRO_MAX_DURATION_SECONDS = 10

ALLOWED_OUTRO_CONTENT_TYPES: frozenset[str] = frozenset(
    {"video/mp4", "video/quicktime"}
)
SUFFIX_BY_OUTRO_CONTENT_TYPE: dict[str, str] = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
}


@dataclass(frozen=True, slots=True)
class UploadOutroVideoInput:
    agency_id: str
    content_type: str
    body: bytes


@dataclass(frozen=True, slots=True)
class OutroValidationResult:
    """Outcome of the pure validation pass over the raw upload payload."""

    content_type: str
    extension: str


def validate_outro_upload(
    *,
    content_type: str,
    body: bytes,
    max_upload_bytes: int = OUTRO_MAX_UPLOAD_BYTES,
) -> OutroValidationResult:
    """Validate MIME + size for an outro upload (pure, no I/O).

    Duration is validated downstream once the bytes are on disk and
    ``ffprobe`` can read them.

    Raises :class:`shared.errors.ValidationError` with ``code`` set to
    ``OUTRO_INVALID_MIME`` (HTTP 422) or ``OUTRO_FILE_TOO_LARGE`` (HTTP
    413) so the router can translate consistently.
    """
    normalized_ct = (content_type or "").strip().lower()
    if normalized_ct not in ALLOWED_OUTRO_CONTENT_TYPES:
        raise ValidationError(
            "Outro upload requires an MP4 or MOV video.",
            code="OUTRO_INVALID_MIME",
            hint="Re-encode the video as video/mp4 or video/quicktime and try again.",
            context={
                "received_content_type": content_type or "",
                "allowed_content_types": sorted(ALLOWED_OUTRO_CONTENT_TYPES),
            },
        )
    if not body:
        raise ValidationError(
            "Outro upload payload is empty.",
            code="OUTRO_FILE_EMPTY",
        )
    if len(body) > max_upload_bytes:
        raise ValidationError(
            "Outro upload exceeds the 50 MB size limit.",
            code="OUTRO_FILE_TOO_LARGE",
            context={
                "received_bytes": len(body),
                "max_bytes": max_upload_bytes,
            },
        )
    return OutroValidationResult(
        content_type=normalized_ct,
        extension=SUFFIX_BY_OUTRO_CONTENT_TYPE[normalized_ct],
    )


def validate_outro_duration(duration_seconds: int) -> int:
    """Validate that the probed duration falls in the allowed window."""
    if duration_seconds < OUTRO_MIN_DURATION_SECONDS or duration_seconds > OUTRO_MAX_DURATION_SECONDS:
        raise ValidationError(
            "Outro duration must be between 1 and 10 seconds.",
            code="OUTRO_INVALID_DURATION",
            hint=(
                "Trim the outro so its duration is between "
                f"{OUTRO_MIN_DURATION_SECONDS} and "
                f"{OUTRO_MAX_DURATION_SECONDS} seconds."
            ),
            context={"duration_seconds": int(duration_seconds)},
        )
    return int(duration_seconds)


class UploadOutroVideoUseCase:
    """Persist an outro binary, probe its duration and register the row."""

    def __init__(
        self,
        *,
        workspace_dir: Path,
        ffprobe_runner=None,
        max_upload_bytes: int = OUTRO_MAX_UPLOAD_BYTES,
    ) -> None:
        self._workspace_dir = Path(workspace_dir).expanduser().resolve()
        self._ffprobe_runner = ffprobe_runner or _run_ffprobe_duration
        self._max_upload_bytes = max_upload_bytes

    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        data: UploadOutroVideoInput,
    ) -> IntroOutroAsset:
        ensure_agency_exists(uow, data.agency_id)
        validation = validate_outro_upload(
            content_type=data.content_type,
            body=data.body,
            max_upload_bytes=self._max_upload_bytes,
        )

        digest = _sha1_hex(data.body)
        filename = f"outro-{digest}{validation.extension}"
        object_key, destination = resolve_agency_intro_outro_destination(
            workspace_dir=self._workspace_dir,
            agency_id=data.agency_id,
            kind="outro",
            filename=filename,
        )

        previous = (
            uow.configuration.intro_outro_assets.get(
                agency_id=data.agency_id, kind="outro"
            )
            if uow.configuration is not None
            else None
        )

        _write_atomic(destination, data.body)

        try:
            duration = self._ffprobe_runner(destination)
        except _FfprobeUnavailableError as error:
            _safe_unlink(destination)
            raise ValidationError(
                "ffprobe is not available on the server; cannot derive the "
                "outro duration.",
                code="OUTRO_PROBE_UNAVAILABLE",
                hint=(
                    "Install ffprobe (ships with ffmpeg) and ensure it is on "
                    "PATH for the API process."
                ),
                context={"error": str(error)},
            )
        except _FfprobeFailedError as error:
            _safe_unlink(destination)
            raise ValidationError(
                "ffprobe could not probe the uploaded outro video.",
                code="OUTRO_PROBE_FAILED",
                hint="Re-encode the video as MP4 or MOV and retry.",
                context={"error": str(error)},
            )

        try:
            validate_outro_duration(duration)
        except ValidationError:
            _safe_unlink(destination)
            raise

        assert uow.configuration is not None  # invariant: caller opened the UoW
        asset = uow.configuration.intro_outro_assets.upsert_uploaded(
            agency_id=data.agency_id,
            kind="outro",
            object_key=object_key,
            duration_seconds=int(duration),
        )

        if (
            previous is not None
            and previous.source == "uploaded"
            and previous.object_key
            and previous.object_key != object_key
        ):
            _safe_unlink_object_key(self._workspace_dir, previous.object_key)

        return asset


class _FfprobeUnavailableError(RuntimeError):
    """Raised when no ``ffprobe`` binary can be located on PATH."""


class _FfprobeFailedError(RuntimeError):
    """Raised when ``ffprobe`` exits non-zero on the uploaded file."""


_DURATION_LINE_RE = re.compile(r"^\s*([\d.]+)\s*$")


def _run_ffprobe_duration(path: Path) -> int:
    binary = shutil.which("ffprobe")
    if not binary:
        raise _FfprobeUnavailableError("ffprobe binary not found on PATH")
    completed = subprocess.run(  # nosec B603 — fixed argv, path is os-managed
        [
            binary,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise _FfprobeFailedError(
            (completed.stderr or "ffprobe failed").strip()
        )
    match = _DURATION_LINE_RE.search(completed.stdout or "")
    if match is None:
        raise _FfprobeFailedError(
            f"ffprobe returned an unparseable duration: {completed.stdout!r}"
        )
    try:
        seconds = float(match.group(1))
    except ValueError as exc:
        raise _FfprobeFailedError(str(exc)) from exc
    return int(round(seconds))


def _sha1_hex(body: bytes) -> str:
    import hashlib

    return hashlib.sha1(body).hexdigest()[:16]


def _write_atomic(destination: Path, body: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_descriptor, tmp_path = tempfile.mkstemp(
        prefix=destination.name + ".",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    try:
        with os.fdopen(tmp_descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, destination)
    except Exception:
        _safe_unlink(Path(tmp_path))
        raise


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:  # pragma: no cover — defensive against permission races
        logger.exception("Failed to clean up uploaded outro blob at %s", path)


def _safe_unlink_object_key(workspace_dir: Path, object_key: str) -> None:
    """Best-effort delete of a previously persisted outro blob."""
    if not object_key:
        return
    # The reverse lookup tolerates the file already being gone (returns None);
    # use a manual reconstruction so we still cleanly handle the case where the
    # ``object_key`` no longer matches the canonical shape (e.g. legacy or S3).
    path = resolve_agency_intro_outro_local_path(
        workspace_dir=workspace_dir,
        object_key=object_key,
    )
    if path is not None:
        _safe_unlink(path)
        return
    # Fallback: rebuild the FS path from the canonical object_key shape so the
    # cleanup still runs when ``resolve_agency_intro_outro_local_path`` returns
    # ``None`` because the file vanished between get() and unlink().
    parts = [part for part in object_key.split("/") if part]
    if len(parts) < 4 or parts[0] != "agencies" or parts[2] not in {"intro", "outro"}:
        return
    safe_agency = parts[1]
    kind = parts[2]
    dirname = "_agency_outro" if kind == "outro" else "_agency_intro"
    rebuilt = workspace_dir / "generated_media" / dirname / safe_agency
    for fragment in parts[3:]:
        rebuilt = rebuilt / fragment
    _safe_unlink(rebuilt)
    # Silence the unused-import warning for ``safe_site_dirname``: we depend
    # on the canonical layout already encoded by the resolver above.
    _ = safe_site_dirname


__all__ = [
    "ALLOWED_OUTRO_CONTENT_TYPES",
    "OUTRO_MAX_UPLOAD_BYTES",
    "OUTRO_MAX_DURATION_SECONDS",
    "OUTRO_MIN_DURATION_SECONDS",
    "OutroValidationResult",
    "SUFFIX_BY_OUTRO_CONTENT_TYPE",
    "UploadOutroVideoInput",
    "UploadOutroVideoUseCase",
    "validate_outro_duration",
    "validate_outro_upload",
]
