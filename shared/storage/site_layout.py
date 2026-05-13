"""Cross-cutting site storage layout helpers.

Migrated from ``services/media/site_storage.py`` during sub-feature 18c.
Resolves on-disk roots for the workspace per tenant, including filtered
images, raw images and generated media (reels, posters, scripted videos).
"""

from __future__ import annotations

import re
from pathlib import Path

from settings import PROPERTY_MEDIA_RAW_ROOT_DIRNAME, PROPERTY_MEDIA_ROOT_DIRNAME
from modules.tenancy.domain.storage import SiteStorageLayout

_INVALID_SITE_DIR_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")
GENERATED_MEDIA_ROOT_DIRNAME = "generated_media"
GENERATED_MEDIA_REELS_DIRNAME = "reels"
GENERATED_MEDIA_POSTERS_DIRNAME = "posters"
GENERATED_MEDIA_SCRIPTED_VIDEOS_DIRNAME = "scripted_videos"
GENERATED_MEDIA_SCRIPTED_ASSETS_DIRNAME = "scripted_assets"
AGENCY_BRANDING_UPLOAD_DIRNAME = "_agency_branding"


def safe_site_dirname(site_id: str) -> str:
    cleaned = _INVALID_SITE_DIR_CHARS_RE.sub("_", site_id.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "site"


def resolve_agency_branding_destination(
    *,
    workspace_dir: Path,
    agency_id: str,
    filename: str,
) -> tuple[str, Path]:
    """Resolve the persistent destination for an admin-uploaded agency asset.

    Returns the tuple ``(object_key, local_path)`` so callers can persist
    ``object_key`` opaquely in the database while writing the binary to
    ``local_path``. The layout uses a per-agency directory under
    ``workspace_dir/generated_media/_agency_branding/{safe_agency}/`` keeping
    the upload independent of any site/property cache. The signature is
    intentionally agnostic of the storage backend so a future S3
    implementation can return an ``s3://...`` object_key plus a download
    cache path without breaking the caller contract.
    """
    safe_agency = safe_site_dirname(agency_id)
    branding_dir = (
        workspace_dir
        / GENERATED_MEDIA_ROOT_DIRNAME
        / AGENCY_BRANDING_UPLOAD_DIRNAME
        / safe_agency
    )
    branding_dir.mkdir(parents=True, exist_ok=True)
    local_path = branding_dir / filename
    object_key = f"agencies/{safe_agency}/{filename}"
    return object_key, local_path


def resolve_agency_branding_local_path(
    *,
    workspace_dir: Path,
    object_key: str,
) -> Path | None:
    """Resolve a previously persisted agency-branding ``object_key``.

    Returns the absolute local path if the file exists on disk; ``None``
    otherwise. The current FS-only backend expects ``object_key`` to be
    shaped as ``agencies/{safe_agency}/{filename}``. Unknown shapes (for
    example future ``s3://...`` keys, empty strings, or paths with ``..``
    traversal) return ``None`` so callers fall back to the legacy webhook
    URL.
    """
    cleaned = str(object_key or "").strip()
    if not cleaned:
        return None
    if "://" in cleaned:
        return None
    parts = [part for part in cleaned.split("/") if part]
    if not parts or parts[0] != "agencies":
        return None
    if any(part in {"..", "."} for part in parts):
        return None
    local_path = workspace_dir / GENERATED_MEDIA_ROOT_DIRNAME / AGENCY_BRANDING_UPLOAD_DIRNAME
    for part in parts[1:]:
        local_path = local_path / part
    if not local_path.exists() or not local_path.is_file():
        return None
    return local_path


def resolve_site_storage_layout(base_dir: str | Path, site_id: str) -> SiteStorageLayout:
    workspace_dir = Path(base_dir).expanduser().resolve()
    safe_site_dir = safe_site_dirname(site_id)
    return SiteStorageLayout(
        workspace_dir=workspace_dir,
        site_id=site_id,
        safe_site_dir=safe_site_dir,
        filtered_images_root=workspace_dir / PROPERTY_MEDIA_ROOT_DIRNAME / safe_site_dir,
        raw_images_root=workspace_dir / PROPERTY_MEDIA_RAW_ROOT_DIRNAME / safe_site_dir,
        generated_media_root=workspace_dir / GENERATED_MEDIA_ROOT_DIRNAME / safe_site_dir,
        generated_reels_root=workspace_dir / GENERATED_MEDIA_ROOT_DIRNAME / safe_site_dir / GENERATED_MEDIA_REELS_DIRNAME,
        generated_posters_root=workspace_dir / GENERATED_MEDIA_ROOT_DIRNAME / safe_site_dir / GENERATED_MEDIA_POSTERS_DIRNAME,
        scripted_videos_root=workspace_dir / GENERATED_MEDIA_ROOT_DIRNAME / safe_site_dir / GENERATED_MEDIA_SCRIPTED_VIDEOS_DIRNAME,
        scripted_assets_root=workspace_dir / GENERATED_MEDIA_ROOT_DIRNAME / safe_site_dir / GENERATED_MEDIA_SCRIPTED_ASSETS_DIRNAME,
        reels_root=workspace_dir / GENERATED_MEDIA_ROOT_DIRNAME / safe_site_dir / GENERATED_MEDIA_REELS_DIRNAME,
    )


__all__ = [
    "AGENCY_BRANDING_UPLOAD_DIRNAME",
    "GENERATED_MEDIA_POSTERS_DIRNAME",
    "GENERATED_MEDIA_REELS_DIRNAME",
    "GENERATED_MEDIA_ROOT_DIRNAME",
    "GENERATED_MEDIA_SCRIPTED_ASSETS_DIRNAME",
    "GENERATED_MEDIA_SCRIPTED_VIDEOS_DIRNAME",
    "SiteStorageLayout",
    "resolve_agency_branding_destination",
    "resolve_agency_branding_local_path",
    "resolve_site_storage_layout",
    "safe_site_dirname",
]
