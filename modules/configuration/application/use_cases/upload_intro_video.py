"""Upload an intro video binary, probe its duration and persist the row.

Feature 34: symmetric to :mod:`upload_outro_video` from feature 33.
The SaaS admin is trusted: the only validations the backend still
enforces are the MIME allow-list and the "body must not be empty"
guard. Size and duration limits were removed deliberately so the admin
can upload intros of any length and weight.

Steps:

1. Validate ``content_type`` against the allowed MIME set
   (``video/mp4`` / ``video/quicktime``).
2. Validate the body is not empty.
3. Write the binary to disk atomically via
   :func:`shared.storage.site_layout.resolve_agency_intro_outro_destination`
   with ``kind='intro'``.
4. Probe duration with ``ffprobe``. The duration is persisted on the
   row for downstream features (rendering, defaults endpoint) but it
   is no longer validated against a range.
5. Persist the row in ``agency_intro_outro_assets`` (``kind='intro'``)
   via the UoW. Drop any prior blob from disk after a successful
   overwrite so the workspace never accumulates orphans.

The HTTP-facing error codes (``INTRO_INVALID_MIME``,
``INTRO_FILE_EMPTY``, ``INTRO_PROBE_UNAVAILABLE``,
``INTRO_PROBE_FAILED``) are surfaced as ``ValidationError(code=...)``
so the router can translate them to 422 deterministically.
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
)

logger = logging.getLogger(__name__)

ALLOWED_INTRO_CONTENT_TYPES: frozenset[str] = frozenset(
    {"video/mp4", "video/quicktime"}
)
SUFFIX_BY_INTRO_CONTENT_TYPE: dict[str, str] = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
}


@dataclass(frozen=True, slots=True)
class UploadIntroVideoInput:
    agency_id: str
    content_type: str
    body: bytes


@dataclass(frozen=True, slots=True)
class IntroValidationResult:
    """Outcome of the pure validation pass over the raw upload payload."""

    content_type: str
    extension: str


def validate_intro_upload(
    *,
    content_type: str,
    body: bytes,
) -> IntroValidationResult:
    """Validate MIME + non-empty body for an intro upload (pure, no I/O).

    Duration is derived downstream once the bytes are on disk and
    ``ffprobe`` can read them, but it is no longer validated against a
    range — the SaaS admin can upload intros of any length.

    Raises :class:`shared.errors.ValidationError` with ``code`` set to
    ``INTRO_INVALID_MIME`` or ``INTRO_FILE_EMPTY`` so the router can
    translate consistently (HTTP 422).
    """
    normalized_ct = (content_type or "").strip().lower()
    if normalized_ct not in ALLOWED_INTRO_CONTENT_TYPES:
        raise ValidationError(
            "Intro upload requires an MP4 or MOV video.",
            code="INTRO_INVALID_MIME",
            hint="Re-encode the video as video/mp4 or video/quicktime and try again.",
            context={
                "received_content_type": content_type or "",
                "allowed_content_types": sorted(ALLOWED_INTRO_CONTENT_TYPES),
            },
        )
    if not body:
        raise ValidationError(
            "Intro upload payload is empty.",
            code="INTRO_FILE_EMPTY",
        )
    return IntroValidationResult(
        content_type=normalized_ct,
        extension=SUFFIX_BY_INTRO_CONTENT_TYPE[normalized_ct],
    )


class UploadIntroVideoUseCase:
    """Persist an intro binary, probe its duration and register the row."""

    def __init__(
        self,
        *,
        workspace_dir: Path,
        ffprobe_runner=None,
    ) -> None:
        self._workspace_dir = Path(workspace_dir).expanduser().resolve()
        self._ffprobe_runner = ffprobe_runner or _run_ffprobe_duration

    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        data: UploadIntroVideoInput,
    ) -> IntroOutroAsset:
        ensure_agency_exists(uow, data.agency_id)
        validation = validate_intro_upload(
            content_type=data.content_type,
            body=data.body,
        )

        digest = _sha1_hex(data.body)
        filename = f"intro-{digest}{validation.extension}"
        object_key, destination = resolve_agency_intro_outro_destination(
            workspace_dir=self._workspace_dir,
            agency_id=data.agency_id,
            kind="intro",
            filename=filename,
        )

        previous = (
            uow.configuration.intro_outro_assets.get(
                agency_id=data.agency_id, kind="intro"
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
                "intro duration.",
                code="INTRO_PROBE_UNAVAILABLE",
                hint=(
                    "Install ffprobe (ships with ffmpeg) and ensure it is on "
                    "PATH for the API process."
                ),
                context={"error": str(error)},
            )
        except _FfprobeFailedError as error:
            _safe_unlink(destination)
            raise ValidationError(
                "ffprobe could not probe the uploaded intro video.",
                code="INTRO_PROBE_FAILED",
                hint="Re-encode the video as MP4 or MOV and retry.",
                context={"error": str(error)},
            )

        assert uow.configuration is not None  # invariant: caller opened the UoW
        asset = uow.configuration.intro_outro_assets.upsert_uploaded(
            agency_id=data.agency_id,
            kind="intro",
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
        logger.exception("Failed to clean up uploaded intro blob at %s", path)


def _safe_unlink_object_key(workspace_dir: Path, object_key: str) -> None:
    """Best-effort delete of a previously persisted intro blob."""
    if not object_key:
        return
    path = resolve_agency_intro_outro_local_path(
        workspace_dir=workspace_dir,
        object_key=object_key,
    )
    if path is not None:
        _safe_unlink(path)
        return
    parts = [part for part in object_key.split("/") if part]
    if len(parts) < 4 or parts[0] != "agencies" or parts[2] not in {"intro", "outro"}:
        return
    safe_agency = parts[1]
    kind = parts[2]
    dirname = "_agency_intro" if kind == "intro" else "_agency_outro"
    rebuilt = workspace_dir / "generated_media" / dirname / safe_agency
    for fragment in parts[3:]:
        rebuilt = rebuilt / fragment
    _safe_unlink(rebuilt)


__all__ = [
    "ALLOWED_INTRO_CONTENT_TYPES",
    "IntroValidationResult",
    "SUFFIX_BY_INTRO_CONTENT_TYPE",
    "UploadIntroVideoInput",
    "UploadIntroVideoUseCase",
    "validate_intro_upload",
]
