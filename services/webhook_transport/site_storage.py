from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from config import DATABASE_FILENAME, PROPERTY_MEDIA_RAW_ROOT_DIRNAME, PROPERTY_MEDIA_ROOT_DIRNAME

_INVALID_SITE_DIR_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")
GENERATED_MEDIA_ROOT_DIRNAME = "generated_media"
GENERATED_MEDIA_REELS_DIRNAME = "reels"
GENERATED_MEDIA_POSTERS_DIRNAME = "posters"


def safe_site_dirname(site_id: str) -> str:
    cleaned = _INVALID_SITE_DIR_CHARS_RE.sub("_", site_id.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "site"


@dataclass(frozen=True, slots=True)
class SiteStorageLayout:
    workspace_dir: Path
    database_path: Path
    site_id: str
    safe_site_dir: str
    filtered_images_root: Path
    raw_images_root: Path
    generated_media_root: Path
    generated_reels_root: Path
    generated_posters_root: Path
    reels_root: Path


def resolve_site_storage_layout(base_dir: str | Path, site_id: str) -> SiteStorageLayout:
    workspace_dir = Path(base_dir).expanduser().resolve()
    safe_site_dir = safe_site_dirname(site_id)
    return SiteStorageLayout(
        workspace_dir=workspace_dir,
        database_path=workspace_dir / DATABASE_FILENAME,
        site_id=site_id,
        safe_site_dir=safe_site_dir,
        filtered_images_root=workspace_dir / PROPERTY_MEDIA_ROOT_DIRNAME / safe_site_dir,
        raw_images_root=workspace_dir / PROPERTY_MEDIA_RAW_ROOT_DIRNAME / safe_site_dir,
        generated_media_root=workspace_dir / GENERATED_MEDIA_ROOT_DIRNAME / safe_site_dir,
        generated_reels_root=workspace_dir / GENERATED_MEDIA_ROOT_DIRNAME / safe_site_dir / GENERATED_MEDIA_REELS_DIRNAME,
        generated_posters_root=workspace_dir / GENERATED_MEDIA_ROOT_DIRNAME / safe_site_dir / GENERATED_MEDIA_POSTERS_DIRNAME,
        reels_root=workspace_dir / GENERATED_MEDIA_ROOT_DIRNAME / safe_site_dir / GENERATED_MEDIA_REELS_DIRNAME,
    )


__all__ = [
    "GENERATED_MEDIA_POSTERS_DIRNAME",
    "GENERATED_MEDIA_REELS_DIRNAME",
    "GENERATED_MEDIA_ROOT_DIRNAME",
    "SiteStorageLayout",
    "resolve_site_storage_layout",
    "safe_site_dirname",
]

