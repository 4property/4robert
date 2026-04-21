from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SiteStorageLayout:
    workspace_dir: Path
    site_id: str
    safe_site_dir: str
    filtered_images_root: Path
    raw_images_root: Path
    generated_media_root: Path
    generated_reels_root: Path
    generated_posters_root: Path
    scripted_videos_root: Path
    scripted_assets_root: Path
    reels_root: Path


__all__ = ["SiteStorageLayout"]
