"""Seed default NCS music tracks for every existing agency.

Feature 23 wires the rendering pipeline to consume ``agency_music_tracks``
instead of the legacy ``assets/music/`` filesystem scan. This migration
backfills the per-agency pool for every agency that already exists at
the moment ``alembic upgrade head`` runs.

Behaviour per agency:

* Skip when at least one row already exists in ``agency_music_tracks``
  (idempotent — never overwrites custom uploads or a previous seed).
* For each entry in :data:`DEFAULT_NCS_MUSIC_TRACK_SEEDS`, copy the
  source ``.mp3`` from ``<repo>/assets/music/`` to
  ``<workspace>/generated_media/_agency_music/<safe_agency>/_seed_ncs_*.mp3``
  via :func:`shared.storage.site_layout.resolve_agency_music_destination`.
* Insert one row with ``is_default=TRUE``, the canonical ``display_name``
  and the ``object_key`` returned by the destination helper.

Workspace resolution: the migration runs outside the API process, so
there is no ``app_factory`` to feed it ``resolved_workspace``. We
default to the repo root (= ``apps.api`` default when ``WORKSPACE_DIR``
is not set in env). Operators with a different workspace must export
``REELS_WORKSPACE_DIR`` before ``alembic upgrade head``. ffprobe is
invoked best-effort to fill ``duration_seconds``; absence falls back
to 0 and the upload endpoint backfills accurate values on first
overwrite.

Downgrade strategy: the migration deletes only rows whose ``object_key``
matches ``agencies/%/music/_seed_ncs_%`` — uploads via
``POST /music/upload`` use unprefixed filenames and survive the
downgrade. The corresponding blobs on disk are also removed.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess  # nosec B404 — fixed argv calls to ffprobe
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision = "20260514_0005"
down_revision = "20260514_0004"
branch_labels = None
depends_on = None


logger = logging.getLogger("alembic.runtime.migration")


# Mirror of modules.configuration.domain.default_music_tracks. Copied
# here on purpose: alembic migrations should be self-contained so they
# keep working even if the canonical Python module is refactored later.
SEED_FILENAME_PREFIX = "_seed_ncs_"
DEFAULT_NCS_MUSIC_TRACK_SEEDS: tuple[tuple[str, str, str], ...] = (
    (
        "N3b, Extra Terra - Silence [NCS Release].mp3",
        "Silence (N3b, Extra Terra)",
        f"{SEED_FILENAME_PREFIX}silence.mp3",
    ),
    (
        "ncs-music.mp3",
        "NCS Default",
        f"{SEED_FILENAME_PREFIX}ncs_default.mp3",
    ),
    (
        "sumu - apart [NCS Release].mp3",
        "Apart (sumu)",
        f"{SEED_FILENAME_PREFIX}apart.mp3",
    ),
    (
        "Sunny Lukas, Zushi & Vanko - Underrated (Feat. Sunny Lukas) [NCS Release].mp3",
        "Underrated (Sunny Lukas, Zushi & Vanko)",
        f"{SEED_FILENAME_PREFIX}underrated.mp3",
    ),
)

_INVALID_SITE_DIR_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")
_GENERATED_MEDIA_ROOT_DIRNAME = "generated_media"
_AGENCY_MUSIC_UPLOAD_DIRNAME = "_agency_music"
_FFPROBE_DURATION_RE = re.compile(r"^\s*([\d.]+)\s*$")


def _safe_site_dirname(site_id: str) -> str:
    cleaned = _INVALID_SITE_DIR_CHARS_RE.sub("_", site_id.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "site"


def _resolve_workspace_dir() -> Path:
    override = os.environ.get("REELS_WORKSPACE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    # alembic/versions/<file>.py → parents[2] is the repo root, same default
    # used by apps.api.app_factory.create_application when workspace_dir is
    # not provided.
    return Path(__file__).resolve().parents[2]


def _resolve_destination(workspace_dir: Path, agency_id: str, filename: str) -> tuple[str, Path]:
    safe_agency = _safe_site_dirname(agency_id)
    music_dir = (
        workspace_dir
        / _GENERATED_MEDIA_ROOT_DIRNAME
        / _AGENCY_MUSIC_UPLOAD_DIRNAME
        / safe_agency
    )
    music_dir.mkdir(parents=True, exist_ok=True)
    local_path = music_dir / filename
    object_key = f"agencies/{safe_agency}/music/{filename}"
    return object_key, local_path


def _probe_duration_seconds(path: Path) -> int:
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
    except (OSError, subprocess.SubprocessError):
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


def upgrade() -> None:
    bind = op.get_bind()
    workspace_dir = _resolve_workspace_dir()
    repo_assets_music = Path(__file__).resolve().parents[2] / "assets" / "music"

    agencies = bind.execute(sa.text("SELECT id FROM agencies")).all()
    for (agency_id,) in agencies:
        agency_id_str = str(agency_id)
        existing = bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM agency_music_tracks "
                "WHERE agency_id = :agency_id"
            ),
            {"agency_id": agency_id_str},
        ).scalar() or 0
        if int(existing) > 0:
            continue

        for source_basename, display_name, destination_basename in DEFAULT_NCS_MUSIC_TRACK_SEEDS:
            source_path = repo_assets_music / source_basename
            if not source_path.is_file():
                logger.warning(
                    "Skipping seed for agency %s: source file %s is missing.",
                    agency_id_str,
                    source_path,
                )
                continue
            object_key, destination_path = _resolve_destination(
                workspace_dir, agency_id_str, destination_basename
            )
            try:
                blob = source_path.read_bytes()
            except OSError as error:
                logger.warning(
                    "Skipping seed for agency %s: failed to read %s (%s).",
                    agency_id_str,
                    source_path,
                    error,
                )
                continue
            if not destination_path.exists() or destination_path.stat().st_size == 0:
                destination_path.write_bytes(blob)
            duration = _probe_duration_seconds(destination_path)
            bind.execute(
                sa.text(
                    "INSERT INTO agency_music_tracks ("
                    "id, agency_id, display_name, object_key, duration_seconds, "
                    "is_default, created_at"
                    ") VALUES ("
                    ":id, :agency_id, :display_name, :object_key, :duration_seconds, "
                    ":is_default, :created_at"
                    ")"
                ),
                {
                    "id": str(uuid4()),
                    "agency_id": agency_id_str,
                    "display_name": display_name,
                    "object_key": object_key,
                    "duration_seconds": duration,
                    "is_default": True,
                    "created_at": datetime.now(timezone.utc),
                },
            )


def downgrade() -> None:
    bind = op.get_bind()
    workspace_dir = _resolve_workspace_dir()

    # Remove rows seeded by upgrade(); user uploads survive because their
    # object_keys never carry the _seed_ncs_ marker.
    seeded_rows = bind.execute(
        sa.text(
            "SELECT agency_id, object_key FROM agency_music_tracks "
            "WHERE object_key LIKE :pattern"
        ),
        {"pattern": f"agencies/%/music/{SEED_FILENAME_PREFIX}%"},
    ).all()
    bind.execute(
        sa.text(
            "DELETE FROM agency_music_tracks WHERE object_key LIKE :pattern"
        ),
        {"pattern": f"agencies/%/music/{SEED_FILENAME_PREFIX}%"},
    )

    # Best-effort blob cleanup. Failure to unlink does NOT abort the
    # downgrade; the next upgrade will overwrite identically-named blobs.
    for _agency_id, object_key in seeded_rows:
        parts = [part for part in str(object_key).split("/") if part]
        if len(parts) < 4 or parts[0] != "agencies" or parts[2] != "music":
            continue
        local_path = workspace_dir / _GENERATED_MEDIA_ROOT_DIRNAME / _AGENCY_MUSIC_UPLOAD_DIRNAME
        for part in parts[1:2] + parts[3:]:
            local_path = local_path / part
        try:
            local_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Failed to unlink seeded music blob: %s", local_path)
