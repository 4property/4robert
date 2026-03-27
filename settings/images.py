from __future__ import annotations


IMAGE_HEADERS = {
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "User-Agent": "Mozilla/5.0 (compatible; CPIHED/1.0)",
}
PROPERTY_MEDIA_ROOT_DIRNAME = "property_media"
PROPERTY_MEDIA_RAW_ROOT_DIRNAME = "property_media_raw"
RAW_PHOTOS_DIRNAME = "raw_photos"
DEFAULT_PROPERTY_FOLDERS = ("property-1", "property-2", "property-3")
SELECTED_PHOTOS_DIRNAME = "selected_photos"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}


__all__ = [
    "DEFAULT_PROPERTY_FOLDERS",
    "IMAGE_EXTENSIONS",
    "IMAGE_HEADERS",
    "PROPERTY_MEDIA_ROOT_DIRNAME",
    "PROPERTY_MEDIA_RAW_ROOT_DIRNAME",
    "RAW_PHOTOS_DIRNAME",
    "SELECTED_PHOTOS_DIRNAME",
]

