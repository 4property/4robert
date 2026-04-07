from __future__ import annotations

DEFAULT_DELETE_TEMPORARY_FILES = True
DEFAULT_DELETE_SELECTED_PHOTOS = False


def should_cleanup_raw_property_dir(delete_temporary_files: bool | None) -> bool:
    return bool(
        DEFAULT_DELETE_TEMPORARY_FILES if delete_temporary_files is None else delete_temporary_files
    )


def should_cleanup_render_staging_dir(delete_temporary_files: bool | None) -> bool:
    return should_cleanup_raw_property_dir(delete_temporary_files)


def should_cleanup_selected_assets(delete_selected_photos: bool | None) -> bool:
    return bool(
        DEFAULT_DELETE_SELECTED_PHOTOS if delete_selected_photos is None else delete_selected_photos
    )


__all__ = [
    "DEFAULT_DELETE_SELECTED_PHOTOS",
    "DEFAULT_DELETE_TEMPORARY_FILES",
    "should_cleanup_raw_property_dir",
    "should_cleanup_render_staging_dir",
    "should_cleanup_selected_assets",
]
