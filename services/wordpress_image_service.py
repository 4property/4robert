from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from config import (
    DEFAULT_PHOTOS_TO_SELECT,
    IMAGE_HEADERS,
    IMAGE_EXTENSIONS,
    IMAGES_ROOT_DIRNAME,
    RAW_PHOTOS_DIRNAME,
    REQUEST_TIMEOUT_SECONDS,
    SELECTED_PHOTOS_DIRNAME,
)
from models.property import Property
from repositories.wordpress_property_repository import DownloadedImage

PRIMARY_IMAGE_STEM = "primary_image"


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


def _build_primary_image_filename(image_url: str, fallback_path: Path | None = None) -> str:
    parsed = urlparse(image_url)
    suffix = Path(parsed.path).suffix
    if not suffix and fallback_path is not None:
        suffix = fallback_path.suffix
    if not suffix:
        suffix = ".jpg"
    return f"{PRIMARY_IMAGE_STEM}{suffix.lower()}"


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


def _list_image_files(folder: Path) -> list[Path]:
    return sorted(
        candidate
        for candidate in folder.iterdir()
        if candidate.is_file() and candidate.suffix.lower() in IMAGE_EXTENSIONS
    )


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


def _prepare_primary_image(
    property_item: Property,
    filtered_property_dir: Path,
    downloaded_images: list[DownloadedImage],
) -> tuple[list[DownloadedImage], Path | None]:
    if not property_item.featured_image_url:
        return downloaded_images, None

    temp_primary_path = filtered_property_dir / (
        f"_tmp_{_build_primary_image_filename(property_item.featured_image_url)}"
    )
    if temp_primary_path.exists():
        temp_primary_path.unlink()

    for index, (position, image_url, local_path) in enumerate(downloaded_images):
        if image_url != property_item.featured_image_url or local_path is None:
            continue

        shutil.move(str(local_path), temp_primary_path)
        downloaded_images[index] = (position, image_url, temp_primary_path)
        return downloaded_images, temp_primary_path

    try:
        _download_image(property_item.featured_image_url, temp_primary_path)
    except Exception as exc:
        print(f"  Failed to prepare primary image {property_item.featured_image_url}: {exc}")
        return downloaded_images, None

    return downloaded_images, temp_primary_path


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
    *,
    primary_image_url: str | None = None,
    primary_selected_path: Path | None = None,
) -> list[DownloadedImage]:
    selected_image_map = _build_selected_image_map(selected_dir, selected_photo_paths)
    filtered_images: list[DownloadedImage] = []
    primary_image_assigned = False

    for position, image_url, local_path in downloaded_images:
        if local_path is None:
            filtered_images.append((position, image_url, None))
            continue

        if (
            not primary_image_assigned
            and primary_selected_path is not None
            and primary_image_url is not None
            and image_url == primary_image_url
        ):
            filtered_images.append((position, image_url, primary_selected_path))
            primary_image_assigned = True
            continue

        filtered_path = selected_image_map.get(local_path.name)
        filtered_images.append((position, image_url, filtered_path))

    return filtered_images


def _move_directory_contents(source_dir: Path, destination_dir: Path) -> None:
    if not source_dir.exists():
        return

    destination_dir.mkdir(parents=True, exist_ok=True)
    for source_path in sorted(source_dir.iterdir()):
        shutil.move(str(source_path), destination_dir / source_path.name)

    source_dir.rmdir()


def _store_primary_image(
    property_item: Property,
    selected_dir: Path,
    temp_primary_path: Path | None,
) -> Path | None:
    if temp_primary_path is None or property_item.featured_image_url is None:
        return None

    selected_dir.mkdir(parents=True, exist_ok=True)
    primary_selected_path = selected_dir / _build_primary_image_filename(
        property_item.featured_image_url,
        temp_primary_path,
    )
    if primary_selected_path.exists():
        primary_selected_path.unlink()
    shutil.move(str(temp_primary_path), primary_selected_path)
    return primary_selected_path


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
    temporary_selected_dir = property_dir / "_selected_photos_tmp"

    downloaded_images = _download_images_to_directory(
        property_item,
        raw_dir,
        overwrite_existing=True,
        show_progress=True,
    )

    if not _has_downloaded_images(downloaded_images):
        _cleanup_raw_property_dir(raw_property_dir)
        return property_dir, downloaded_images

    downloaded_images, temp_primary_path = _prepare_primary_image(
        property_item,
        property_dir,
        downloaded_images,
    )
    primary_selected_path: Path | None = None
    primary_slot_count = 1 if temp_primary_path is not None else 0
    remaining_photo_count = max(photos_to_select - primary_slot_count, 0)

    try:
        selected_photos = []
        remaining_photo_paths = _list_image_files(raw_dir)
        if remaining_photo_count > 0 and remaining_photo_paths:
            selected_photos = filter_photos(
                remaining_photo_count,
                raw_dir,
                temporary_selected_dir,
            )

        selected_dir.mkdir(parents=True, exist_ok=True)
        _move_directory_contents(temporary_selected_dir, selected_dir)
        primary_selected_path = _store_primary_image(
            property_item,
            selected_dir,
            temp_primary_path,
        )
        if primary_selected_path is not None:
            print(f"  Primary image saved as {primary_selected_path.name}.")
        print(f"  Final selected photos folder: {selected_dir}")

        selected_photo_paths = [candidate.path for candidate in selected_photos]
        filtered_images = _build_filtered_image_records(
            downloaded_images,
            selected_dir,
            selected_photo_paths,
            primary_image_url=property_item.featured_image_url,
            primary_selected_path=primary_selected_path,
        )
        return selected_dir, filtered_images
    finally:
        if temporary_selected_dir.exists():
            shutil.rmtree(temporary_selected_dir, ignore_errors=True)
        _cleanup_raw_property_dir(raw_property_dir)


__all__ = [
    "DEFAULT_PHOTOS_TO_SELECT",
    "RAW_PHOTOS_DIRNAME",
    "IMAGES_ROOT_DIRNAME",
    "SELECTED_PHOTOS_DIRNAME",
    "download_property_images",
    "download_and_filter_property_images",
]
