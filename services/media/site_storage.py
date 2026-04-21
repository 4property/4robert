from __future__ import annotations

import re
from pathlib import Path

from settings import PROPERTY_MEDIA_RAW_ROOT_DIRNAME, PROPERTY_MEDIA_ROOT_DIRNAME
from domain.tenancy.storage import SiteStorageLayout

_INVALID_SITE_DIR_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")
GENERATED_MEDIA_ROOT_DIRNAME = "generated_media"
GENERATED_MEDIA_REELS_DIRNAME = "reels"
GENERATED_MEDIA_POSTERS_DIRNAME = "posters"
GENERATED_MEDIA_SCRIPTED_VIDEOS_DIRNAME = "scripted_videos"
GENERATED_MEDIA_SCRIPTED_ASSETS_DIRNAME = "scripted_assets"


def safe_site_dirname(site_id: str) -> str:
    cleaned = _INVALID_SITE_DIR_CHARS_RE.sub("_", site_id.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "site"


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
    "GENERATED_MEDIA_POSTERS_DIRNAME",
    "GENERATED_MEDIA_REELS_DIRNAME",
    "GENERATED_MEDIA_ROOT_DIRNAME",
    "GENERATED_MEDIA_SCRIPTED_ASSETS_DIRNAME",
    "GENERATED_MEDIA_SCRIPTED_VIDEOS_DIRNAME",
    "SiteStorageLayout",
    "resolve_site_storage_layout",
    "safe_site_dirname",
]

