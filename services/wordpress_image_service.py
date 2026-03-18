from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from config import (
    DEFAULT_PHOTOS_TO_SELECT,
    IMAGE_HEADERS,
    IMAGES_ROOT_DIRNAME,
    RAW_PHOTOS_DIRNAME,
    REQUEST_TIMEOUT_SECONDS,
    SELECTED_PHOTOS_DIRNAME,
)
from models.property import Property
from repositories.wordpress_property_repository import DownloadedImage


def _build_request(url: str) -> Request:
    return Request(url, headers=IMAGE_HEADERS)


def _clean_filename(candidate: str) -> str:
    cleaned = "".join(
        character if character not in '<>:"/\\|?*' else "_"
        for character in candidate
    ).strip()
    return cleaned or "image.jpg"


def _build_image_filename(position: int, image_url: str) -> str:
    parsed = urlparse(image_url)
    basename = Path(parsed.path).name or f"image-{position}.jpg"
    return f"{position:03d}_{_clean_filename(basename)}"


def _download_image(image_url: str, destination: Path) -> None:
    with urlopen(_build_request(image_url), timeout=REQUEST_TIMEOUT_SECONDS) as response:
        with destination.open("wb") as file_handle:
            shutil.copyfileobj(response, file_handle)


def _prepare_property_directories(
    raw_images_root: Path,
    filtered_images_root: Path,
    property_item: Property,
    *,
    clear_selected_dir: bool,
) -> tuple[Path, Path, Path, Path]:
    filtered_property_dir = filtered_images_root / property_item.folder_name
    raw_property_dir = raw_images_root / property_item.folder_name
    raw_dir = raw_property_dir / RAW_PHOTOS_DIRNAME
    selected_dir = filtered_property_dir / SELECTED_PHOTOS_DIRNAME

    raw_images_root.mkdir(parents=True, exist_ok=True)
    filtered_images_root.mkdir(parents=True, exist_ok=True)
    raw_property_dir.mkdir(parents=True, exist_ok=True)
    filtered_property_dir.mkdir(parents=True, exist_ok=True)

    if raw_dir.exists():
        shutil.rmtree(raw_dir)
    if clear_selected_dir and selected_dir.exists():
        shutil.rmtree(selected_dir)

    raw_dir.mkdir(parents=True, exist_ok=True)
    return filtered_property_dir, raw_property_dir, raw_dir, selected_dir


def _cleanup_raw_property_dir(raw_property_dir: Path) -> None:
    shutil.rmtree(raw_property_dir, ignore_errors=True)


def _download_images_to_directory(
    property_item: Property,
    destination_dir: Path,
    *,
    overwrite_existing: bool,
    show_progress: bool,
) -> list[DownloadedImage]:
    downloaded_images: list[DownloadedImage] = []

    for position, image_url in enumerate(property_item.image_urls, start=1):
        filename = _build_image_filename(position, image_url)
        destination = destination_dir / filename

        try:
            if show_progress:
                print(f"  Downloading image {position}/{len(property_item.image_urls)}...")
            if overwrite_existing or not destination.exists() or destination.stat().st_size == 0:
                _download_image(image_url, destination)
            downloaded_images.append((position, image_url, destination))
        except Exception as exc:
            print(f"  Failed to download {image_url}: {exc}")
            downloaded_images.append((position, image_url, None))

    return downloaded_images


def _has_downloaded_images(downloaded_images: list[DownloadedImage]) -> bool:
    return any(local_path is not None for _, _, local_path in downloaded_images)


def _build_selected_image_map(
    selected_dir: Path,
    selected_photo_paths: list[Path],
) -> dict[str, Path]:
    return {
        source_path.name: selected_dir / f"{index:02d}_{source_path.name}"
        for index, source_path in enumerate(selected_photo_paths, start=1)
    }


def _build_filtered_image_records(
    downloaded_images: list[DownloadedImage],
    selected_dir: Path,
    selected_photo_paths: list[Path],
) -> list[DownloadedImage]:
    selected_image_map = _build_selected_image_map(selected_dir, selected_photo_paths)
    filtered_images: list[DownloadedImage] = []

    for position, image_url, local_path in downloaded_images:
        if local_path is None:
            filtered_images.append((position, image_url, None))
            continue

        filtered_path = selected_image_map.get(local_path.name)
        filtered_images.append((position, image_url, filtered_path))

    return filtered_images


def download_property_images(
    property_item: Property,
    raw_images_root: Path,
) -> tuple[Path, list[DownloadedImage]]:
    _, raw_property_dir, raw_dir, _ = _prepare_property_directories(
        raw_images_root,
        raw_images_root,
        property_item,
        clear_selected_dir=False,
    )

    downloads = _download_images_to_directory(
        property_item,
        raw_dir,
        overwrite_existing=False,
        show_progress=False,
    )

    if not _has_downloaded_images(downloads):
        _cleanup_raw_property_dir(raw_property_dir)

    return raw_dir, downloads


def download_and_filter_property_images(
    property_item: Property,
    raw_images_root: Path,
    filtered_images_root: Path | None = None,
    photos_to_select: int = DEFAULT_PHOTOS_TO_SELECT,
) -> tuple[Path, list[DownloadedImage]]:
    from services.photo_filter_service import filter_photos

    if filtered_images_root is None:
        filtered_images_root = raw_images_root

    property_dir, raw_property_dir, raw_dir, selected_dir = _prepare_property_directories(
        raw_images_root,
        filtered_images_root,
        property_item,
        clear_selected_dir=True,
    )

    downloaded_images = _download_images_to_directory(
        property_item,
        raw_dir,
        overwrite_existing=True,
        show_progress=True,
    )

    available_photo_paths = [
        local_path
        for _, _, local_path in downloaded_images
        if local_path is not None
    ]
    if not available_photo_paths:
        _cleanup_raw_property_dir(raw_property_dir)
        return property_dir, downloaded_images

    selected_photos = filter_photos(
        photos_to_select,
        raw_dir,
        selected_dir,
    )
    selected_photo_paths = [candidate.path for candidate in selected_photos]
    filtered_images = _build_filtered_image_records(
        downloaded_images,
        selected_dir,
        selected_photo_paths,
    )

    _cleanup_raw_property_dir(raw_property_dir)
    return selected_dir, filtered_images


__all__ = [
    "DEFAULT_PHOTOS_TO_SELECT",
    "RAW_PHOTOS_DIRNAME",
    "IMAGES_ROOT_DIRNAME",
    "SELECTED_PHOTOS_DIRNAME",
    "download_property_images",
    "download_and_filter_property_images",
]
