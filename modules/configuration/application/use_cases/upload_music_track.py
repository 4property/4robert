"""Upload a music track binary, probe its duration and persist the row.

This use case is the application orchestration behind
``POST /v1/admin/agencies/{agency_id}/music/upload`` (feature 22). The
HTTP layer is responsible for parsing the multipart envelope, validating
the content-type / extension and enforcing the upload size cap. By the
time we reach this use case the binary has been validated as audio in
shape and we own the side-effects:

1. Write the binary to disk via ``resolve_agency_music_destination``
   using an atomic ``tempfile + rename`` so a crash mid-write never
   leaves a half-written file under the agency folder.
2. Probe the duration via ``ffprobe`` (subprocess + ``-show_format``);
   on failure raise :class:`shared.errors.ValidationError` with a
   ``MUSIC_TRACK_AUDIO_INVALID`` code so the HTTP layer translates to
   400.
3. Register the row through :class:`RegisterMusicTrackUseCase`; on
   failure we clean up the blob from disk before propagating the error
   so the agency folder never accumulates orphans.

The ``ffprobe`` invocation is local to this module on purpose: the
configuration module must NOT import from ``modules.rendering`` (layer
rules — only domain imports across modules). The binary is resolved via
``shutil.which`` so containers that ship ffprobe in a non-standard
location still work as long as ``$PATH`` is correct.
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

from modules.configuration.application.use_cases.register_music_track import (
    RegisterMusicTrackInput,
    RegisterMusicTrackUseCase,
)
from modules.configuration.domain import MusicTrack
from shared.db import DatabaseUnitOfWork
from shared.errors import ApplicationError, ValidationError
from shared.storage.site_layout import resolve_agency_music_destination

logger = logging.getLogger(__name__)

# 10 minutes — same cap as the existing PUT/POST metadata payloads
# (`MusicTrackPayload.duration_seconds <= 600`).
MUSIC_TRACK_MAX_DURATION_SECONDS = 600


@dataclass(frozen=True, slots=True)
class UploadMusicTrackInput:
    agency_id: str
    filename: str
    body: bytes
    display_name: str
    is_default: bool = False


class UploadMusicTrackUseCase:
    """Persist a music binary, probe its duration and register the row."""

    def __init__(
        self,
        *,
        workspace_dir: Path,
        register_music_track: RegisterMusicTrackUseCase | None = None,
        ffprobe_runner=None,
    ) -> None:
        self._workspace_dir = Path(workspace_dir).expanduser().resolve()
        self._register = register_music_track or RegisterMusicTrackUseCase()
        # ``ffprobe_runner`` is exposed for unit tests so they can stub the
        # subprocess without monkey-patching globals.
        self._ffprobe_runner = ffprobe_runner or _run_ffprobe_duration

    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        data: UploadMusicTrackInput,
    ) -> MusicTrack:
        object_key, destination = resolve_agency_music_destination(
            workspace_dir=self._workspace_dir,
            agency_id=data.agency_id,
            filename=data.filename,
        )
        _write_atomic(destination, data.body)

        try:
            duration = self._ffprobe_runner(destination)
        except _FfprobeUnavailableError as error:
            _safe_unlink(destination)
            raise ValidationError(
                "ffprobe is not available on the server; cannot derive "
                "the track duration.",
                code="MUSIC_TRACK_AUDIO_INVALID",
                hint=(
                    "Install ffprobe (ships with ffmpeg) and ensure it is "
                    "on PATH for the API process."
                ),
                context={"error": str(error)},
            )
        except _FfprobeFailedError as error:
            _safe_unlink(destination)
            raise ValidationError(
                "ffprobe could not probe the uploaded audio file.",
                code="MUSIC_TRACK_AUDIO_INVALID",
                hint=(
                    "Re-encode the audio to a supported format "
                    "(mp3/m4a/wav) and try again."
                ),
                context={"error": str(error)},
            )

        if duration <= 0:
            _safe_unlink(destination)
            raise ValidationError(
                "The uploaded audio has zero duration.",
                code="MUSIC_TRACK_AUDIO_INVALID",
                hint="Upload a non-empty audio file.",
                context={"duration_seconds": duration},
            )
        if duration > MUSIC_TRACK_MAX_DURATION_SECONDS:
            _safe_unlink(destination)
            raise ValidationError(
                "The uploaded audio is longer than the 10-minute limit.",
                code="MUSIC_TRACK_AUDIO_INVALID",
                hint=(
                    "Trim the audio to "
                    f"{MUSIC_TRACK_MAX_DURATION_SECONDS} seconds or less."
                ),
                context={"duration_seconds": duration},
            )

        try:
            track = self._register.execute(
                uow=uow,
                data=RegisterMusicTrackInput(
                    agency_id=data.agency_id,
                    display_name=data.display_name,
                    object_key=object_key,
                    duration_seconds=duration,
                    is_default=bool(data.is_default),
                ),
            )
        except ApplicationError:
            # Persistence failed — drop the orphan blob so the agency
            # folder does not accumulate dead files.
            _safe_unlink(destination)
            raise
        except Exception:
            _safe_unlink(destination)
            raise
        return track


class _FfprobeUnavailableError(RuntimeError):
    """Raised when no ``ffprobe`` binary can be located on PATH."""


class _FfprobeFailedError(RuntimeError):
    """Raised when ``ffprobe`` exits non-zero on the uploaded file."""


_DURATION_LINE_RE = re.compile(r"^\s*([\d.]+)\s*$")


def _run_ffprobe_duration(path: Path) -> int:
    """Return the integer duration in seconds reported by ``ffprobe``.

    Uses ``-show_entries format=duration`` which works for any container
    ffprobe understands (mp3, m4a, wav). Raises
    :class:`_FfprobeUnavailableError` when the binary is missing and
    :class:`_FfprobeFailedError` when ffprobe exits non-zero.
    """
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


def _write_atomic(destination: Path, body: bytes) -> None:
    """Write ``body`` to ``destination`` atomically.

    Uses ``tempfile.NamedTemporaryFile`` in the same directory so the
    final ``os.replace`` is a metadata-only rename on POSIX (no
    cross-device hop) and never leaves the caller staring at a partial
    file mid-crash.
    """
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
    """Best-effort delete that swallows ``FileNotFoundError``/``OSError``."""
    try:
        path.unlink(missing_ok=True)
    except OSError:  # pragma: no cover — defensive against permission races
        logger.exception("Failed to clean up uploaded music blob at %s", path)


__all__ = [
    "MUSIC_TRACK_MAX_DURATION_SECONDS",
    "UploadMusicTrackInput",
    "UploadMusicTrackUseCase",
]
