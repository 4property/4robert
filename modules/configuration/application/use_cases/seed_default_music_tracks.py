"""Seed an agency with the default NCS music track pool.

Feature 23: every agency starts with a curated pool of royalty-free
NCS-released tracks so the reel renderer always has something to play.
The canonical list lives in
:mod:`modules.configuration.domain.default_music_tracks`; this use case
materialises both the database rows and the on-disk blobs for a single
agency.

Two entry points consume this helper:

1. :class:`modules.tenancy.application.use_cases.register_agency.RegisterAgencyUseCase`
   calls it right after persisting a brand new ``agencies`` row so the
   admin lands on a usable music page from day one.
2. The seed migration
   (``20260514_0005_seed_existing_agencies_with_ncs_music_tracks``)
   loops over every existing agency at upgrade time.

Idempotency contract:

* If the agency already has at least one row in ``agency_music_tracks``
  the helper returns early — it never overwrites existing tracks
  (including user uploads via ``POST /v1/admin/agencies/{id}/music/upload``).
* The blob copy uses an atomic ``write_bytes`` to the destination
  returned by :func:`shared.storage.site_layout.resolve_agency_music_destination`
  and silently skips files that already exist (the migration may run
  twice with the same workspace).

The helper takes the workspace_dir explicitly rather than reading it
off the UoW so unit tests can drive it without instantiating the full
DatabaseUnitOfWork. The asset source directory defaults to the project
root ``assets/music/`` because that's where the canonical NCS files
ship with the repo; the override is exposed for tests that want to
point at a fixture directory.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess  # nosec B404 — fixed argv calls to ffprobe
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from modules.configuration.domain import DEFAULT_NCS_MUSIC_TRACK_SEEDS
from shared.storage.site_layout import resolve_agency_music_destination

if TYPE_CHECKING:  # pragma: no cover - import only for type hints
    from shared.db import DatabaseUnitOfWork

logger = logging.getLogger(__name__)


REPO_ASSETS_MUSIC_DIR = Path(__file__).resolve().parents[4] / "assets" / "music"
_FFPROBE_DURATION_RE = re.compile(r"^\s*([\d.]+)\s*$")


def _probe_duration_seconds(path: Path) -> int:
    """Best-effort ffprobe duration; returns 0 when ffprobe unavailable."""
    binary = shutil.which("ffprobe")
    if not binary:
        return 0
    try:
        completed = subprocess.run(  # nosec B603 — fixed argv, path is local
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
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - defensive
        return 0
    if completed.returncode != 0:
        return 0
    match = _FFPROBE_DURATION_RE.search(completed.stdout or "")
    if match is None:
        return 0
    try:
        return int(round(float(match.group(1))))
    except ValueError:
        return 0


def seed_default_music_tracks_for_agency(
    *,
    uow: "DatabaseUnitOfWork",
    agency_id: str,
    workspace_dir: Path,
    source_music_dir: Path | None = None,
) -> int:
    """Seed default NCS music tracks for ``agency_id``; return rows created.

    Returns ``0`` when the agency already has tracks (idempotent skip)
    or when the configuration namespace is missing on the UoW.

    The blob copy stage is silently skipped for any seed entry whose
    source file is missing from ``source_music_dir``. The corresponding
    DB row is also skipped so we never persist a track that points at
    a non-existent blob.
    """
    normalized_agency_id = str(agency_id or "").strip()
    if not normalized_agency_id:
        return 0
    configuration = getattr(uow, "configuration", None)
    if configuration is None:
        return 0
    music_repo = getattr(configuration, "music", None)
    if music_repo is None:
        return 0

    existing_tracks = music_repo.list_for_agency(normalized_agency_id)
    if existing_tracks:
        return 0

    music_source_root = (
        Path(source_music_dir).expanduser().resolve()
        if source_music_dir is not None
        else REPO_ASSETS_MUSIC_DIR
    )

    rows_inserted = 0
    for seed in DEFAULT_NCS_MUSIC_TRACK_SEEDS:
        source_path = music_source_root / seed.source_filename
        if not source_path.is_file():
            logger.warning(
                "Skipping default music seed for agency %s: source file %s is missing.",
                normalized_agency_id,
                source_path,
            )
            continue
        object_key, destination_path = resolve_agency_music_destination(
            workspace_dir=workspace_dir,
            agency_id=normalized_agency_id,
            filename=seed.destination_filename,
        )
        try:
            blob = source_path.read_bytes()
        except OSError as error:
            logger.warning(
                "Skipping default music seed for agency %s: failed to read %s (%s).",
                normalized_agency_id,
                source_path,
                error,
            )
            continue
        if not destination_path.exists() or destination_path.stat().st_size == 0:
            destination_path.write_bytes(blob)

        duration_seconds = _probe_duration_seconds(destination_path)
        music_repo.add_track(
            music_id=str(uuid4()),
            agency_id=normalized_agency_id,
            display_name=seed.display_name,
            object_key=object_key,
            duration_seconds=duration_seconds,
            is_default=True,
        )
        rows_inserted += 1
    return rows_inserted


__all__ = [
    "REPO_ASSETS_MUSIC_DIR",
    "seed_default_music_tracks_for_agency",
]
