from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request

from config import IMAGE_HEADERS

PRIMARY_IMAGE_STEM = "primary_image"
MAX_LOCAL_IMAGE_BASENAME_LENGTH = 72
_LEADING_POSITION_PREFIX_RE = re.compile(r"^\d+_")


def build_request(url: str) -> Request:
    return Request(url, headers=IMAGE_HEADERS)


def clean_filename(candidate: str) -> str:
    cleaned = "".join(
        character if character not in '<>:"/\\|?*' else "_"
        for character in candidate
    ).strip()
    return cleaned or "image.jpg"


def shorten_filename(candidate: str, *, max_length: int = MAX_LOCAL_IMAGE_BASENAME_LENGTH) -> str:
    cleaned = clean_filename(candidate)
    if len(cleaned) <= max_length:
        return cleaned

    suffix = Path(cleaned).suffix.lower()
    stem = Path(cleaned).stem
    digest = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:10]
    reserved_length = len(suffix) + len(digest) + 1
    stem_length = max(max_length - reserved_length, 12)
    shortened_stem = stem[:stem_length].rstrip(" ._-") or "image"
    shortened = f"{shortened_stem}_{digest}{suffix}"
    if len(shortened) <= max_length:
        return shortened
    overflow = len(shortened) - max_length
    shortened_stem = shortened_stem[:-overflow].rstrip(" ._-") or "image"
    return f"{shortened_stem}_{digest}{suffix}"


def normalize_selected_source_name(source_name: str | Path) -> str:
    filename = Path(source_name).name
    normalized = _LEADING_POSITION_PREFIX_RE.sub("", filename)
    return shorten_filename(normalized)


def build_image_filename(position: int, image_url: str) -> str:
    parsed = urlparse(image_url)
    basename = Path(parsed.path).name or f"image-{position}.jpg"
    return f"{position:03d}_{shorten_filename(basename)}"


def build_selected_image_filename(position: int, source_name: str | Path) -> str:
    return f"{position:02d}_{normalize_selected_source_name(source_name)}"


def build_primary_image_filename(image_url: str, fallback_path: Path | None = None) -> str:
    parsed = urlparse(image_url)
    suffix = Path(parsed.path).suffix
    if not suffix and fallback_path is not None:
        suffix = fallback_path.suffix
    if not suffix:
        suffix = ".jpg"
    return f"{PRIMARY_IMAGE_STEM}{suffix.lower()}"


__all__ = [
    "MAX_LOCAL_IMAGE_BASENAME_LENGTH",
    "PRIMARY_IMAGE_STEM",
    "build_image_filename",
    "build_primary_image_filename",
    "build_selected_image_filename",
    "build_request",
    "clean_filename",
    "normalize_selected_source_name",
    "shorten_filename",
]
