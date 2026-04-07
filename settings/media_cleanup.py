from __future__ import annotations

from settings.app import APP_SETTINGS

PROPERTY_MEDIA_DELETE_SELECTED_PHOTOS = APP_SETTINGS.property_media_delete_selected_photos
PROPERTY_MEDIA_DELETE_TEMPORARY_FILES = APP_SETTINGS.property_media_delete_temporary_files

__all__ = [
    "PROPERTY_MEDIA_DELETE_SELECTED_PHOTOS",
    "PROPERTY_MEDIA_DELETE_TEMPORARY_FILES",
]
