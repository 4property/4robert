"""Cleanup policies for raw + temporary on-disk artifacts.

Implementation lives in `shared.media_cleanup.policies`.
"""

from shared.media_cleanup.policies import (
    DEFAULT_DELETE_SELECTED_PHOTOS,
    DEFAULT_DELETE_TEMPORARY_FILES,
    should_cleanup_raw_property_dir,
    should_cleanup_render_staging_dir,
    should_cleanup_selected_assets,
)

__all__ = [
    "DEFAULT_DELETE_SELECTED_PHOTOS",
    "DEFAULT_DELETE_TEMPORARY_FILES",
    "should_cleanup_raw_property_dir",
    "should_cleanup_render_staging_dir",
    "should_cleanup_selected_assets",
]
