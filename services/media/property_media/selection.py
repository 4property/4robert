from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from uuid import uuid4

from settings import DEFAULT_PHOTOS_TO_SELECT, GEMINI_SELECTION_AUDIT_FILENAME
from core.media_cleanup import (
    DEFAULT_DELETE_TEMPORARY_FILES,
    should_cleanup_raw_property_dir,
)
from core.logging import LoggedProcess, format_detail_line
from core.errors import PhotoFilteringError
from domain.properties.model import Property
from domain.media.types import DownloadedImage
from services.ai.photo_selection import GeminiImageRecord, classify_property_images
from services.media.property_media.downloads import download_image, download_images_to_directory, has_downloaded_images
from services.media.property_media.filesystem import (
    cleanup_raw_property_dir,
    list_image_files,
    move_directory_contents,
    prepare_property_directories,
)
from services.media.property_media.naming import build_primary_image_filename
from services.media.property_media.naming import build_selected_image_filename

logger = logging.getLogger(__name__)


def prepare_primary_image(
    property_item: Property,
    filtered_property_dir: Path,
    downloaded_images: list[DownloadedImage],
) -> tuple[list[DownloadedImage], Path | None]:
    if not property_item.featured_image_url:
        return downloaded_images, None

    temp_primary_path = filtered_property_dir / (
        f"_tmp_{build_primary_image_filename(property_item.featured_image_url)}"
    )
    if temp_primary_path.exists():
        temp_primary_path.unlink()

    for index, (position, image_url, local_path) in enumerate(downloaded_images):
        if image_url != property_item.featured_image_url or local_path is None:
            continue

        shutil.move(str(local_path), temp_primary_path)
        downloaded_images[index] = (position, image_url, temp_primary_path)
        logger.info(
            "%s",
            format_detail_line("Featured image source", "Existing downloaded image"),
        )
        return downloaded_images, temp_primary_path

    try:
        download_image(property_item.featured_image_url, temp_primary_path)
        logger.info(
            "%s",
            format_detail_line("Featured image source", "Downloaded separately"),
        )
    except Exception as exc:
        logger.warning(
            "Failed to prepare the featured image for property %s from %s. Error: %s",
            property_item.id,
            property_item.featured_image_url,
            exc,
        )
        return downloaded_images, None

    return downloaded_images, temp_primary_path


def build_selected_image_map(
    selected_dir: Path,
    selected_photo_paths: list[Path],
) -> dict[str, Path]:
    return {
        source_path.name: selected_dir / build_selected_image_filename(index, source_path.name)
        for index, source_path in enumerate(selected_photo_paths, start=1)
    }


def build_filtered_image_records(
    downloaded_images: list[DownloadedImage],
    selected_dir: Path,
    selected_photo_paths: list[Path],
    *,
    primary_image_url: str | None = None,
    primary_selected_path: Path | None = None,
) -> list[DownloadedImage]:
    selected_image_map = build_selected_image_map(selected_dir, selected_photo_paths)
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


def store_primary_image(
    property_item: Property,
    selected_dir: Path,
    temp_primary_path: Path | None,
) -> Path | None:
    if temp_primary_path is None or property_item.featured_image_url is None:
        return None

    selected_dir.mkdir(parents=True, exist_ok=True)
    primary_selected_path = selected_dir / build_primary_image_filename(
        property_item.featured_image_url,
        temp_primary_path,
    )
    if primary_selected_path.exists():
        primary_selected_path.unlink()
    shutil.move(str(temp_primary_path), primary_selected_path)
    return primary_selected_path


def _copy_selected_photo_paths(photo_paths: list[Path], destination_dir: Path) -> None:
    if not photo_paths:
        return

    destination_dir.mkdir(parents=True, exist_ok=True)
    for index, source_path in enumerate(photo_paths, start=1):
        destination_path = destination_dir / build_selected_image_filename(index, source_path.name)
        try:
            shutil.copy2(source_path, destination_path)
        except OSError as exc:
            raise PhotoFilteringError(
                "Failed to copy a selected photo to the staging directory. "
                f"Source: {source_path} (len={len(str(source_path))}) | "
                f"Destination: {destination_path} (len={len(str(destination_path))}) | "
                f"Error: {exc}"
            ) from exc


def _relative_path(path: Path, base_dir: Path) -> str:
    try:
        relative_path = path.resolve().relative_to(base_dir.resolve())
        return str(relative_path).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _resolve_workspace_dir(property_dir: Path) -> Path:
    try:
        return property_dir.parents[2]
    except IndexError:
        return property_dir.parent


def _build_gemini_image_records(
    *,
    property_item: Property,
    property_dir: Path,
    downloaded_images: list[DownloadedImage],
    temp_primary_path: Path | None,
) -> list[GeminiImageRecord]:
    workspace_dir = _resolve_workspace_dir(property_dir)
    image_records: list[GeminiImageRecord] = []
    primary_image_url = property_item.featured_image_url

    if temp_primary_path is not None and primary_image_url:
        primary_index = next(
            (
                position
                for position, image_url, _ in downloaded_images
                if image_url == primary_image_url
            ),
            0,
        )
        image_records.append(
            GeminiImageRecord(
                file=build_primary_image_filename(primary_image_url, temp_primary_path),
                source_url=primary_image_url,
                source_index=primary_index,
                local_path=temp_primary_path,
                relative_path=_relative_path(temp_primary_path, workspace_dir),
                reserved=True,
            )
        )

    for position, image_url, local_path in downloaded_images:
        if local_path is None or local_path == temp_primary_path:
            continue
        image_records.append(
            GeminiImageRecord(
                file=local_path.name,
                source_url=image_url,
                source_index=position,
                local_path=local_path,
                relative_path=_relative_path(local_path, workspace_dir),
            )
        )

    if temp_primary_path is not None and primary_image_url:
        return [image_records[0], *sorted(image_records[1:], key=lambda record: record.source_index)]
    return sorted(image_records, key=lambda record: record.source_index)


def _select_photo_paths(
    *,
    property_item: Property,
    property_dir: Path,
    raw_dir: Path,
    temporary_selected_dir: Path,
    downloaded_images: list[DownloadedImage],
    temp_primary_path: Path | None,
    photos_to_select: int,
) -> list[Path]:
    image_records = _build_gemini_image_records(
        property_item=property_item,
        property_dir=property_dir,
        downloaded_images=downloaded_images,
        temp_primary_path=temp_primary_path,
    )
    if not image_records:
        return []

    workspace_dir = _resolve_workspace_dir(property_dir)
    logger.info(
        "%s",
        format_detail_line("Gemini candidate image count", len(image_records), highlight=True),
    )
    outcome = classify_property_images(
        property_item,
        image_records,
        output_path=property_dir / GEMINI_SELECTION_AUDIT_FILENAME,
        downloads_dir=_relative_path(raw_dir, workspace_dir),
        photos_to_select=photos_to_select,
    )
    _copy_selected_photo_paths(list(outcome.selected_photo_paths), temporary_selected_dir)
    logger.info(
        "Gemini photo selection audit saved for property %s at %s.",
        property_item.id,
        outcome.audit_path,
    )
    return list(outcome.selected_photo_paths)


def download_and_filter_property_images(
    property_item: Property,
    raw_images_root: Path,
    filtered_images_root: Path | None = None,
    photos_to_select: int = DEFAULT_PHOTOS_TO_SELECT,
    cleanup_temporary_files: bool = DEFAULT_DELETE_TEMPORARY_FILES,
) -> tuple[Path, list[DownloadedImage]]:
    started_at = time.perf_counter()
    if filtered_images_root is None:
        filtered_images_root = raw_images_root

    property_dir, raw_property_dir, raw_dir, selected_dir = prepare_property_directories(
        raw_images_root,
        filtered_images_root,
        property_item,
        clear_selected_dir=True,
    )
    temporary_selected_dir = property_dir / f"_seltmp_{uuid4().hex[:8]}"

    with LoggedProcess(
        logger,
        "RAW IMAGE DOWNLOAD",
        (
            format_detail_line("Property ID", property_item.id, highlight=True),
            format_detail_line("Image count", len(property_item.image_urls), highlight=True),
            format_detail_line("Raw directory", raw_dir),
        ),
    ):
        downloaded_images = download_images_to_directory(
            property_item,
            raw_dir,
            overwrite_existing=True,
            show_progress=True,
        )

    if not has_downloaded_images(downloaded_images):
        if should_cleanup_raw_property_dir(cleanup_temporary_files):
            cleanup_raw_property_dir(raw_property_dir)
        return property_dir, downloaded_images

    with LoggedProcess(
        logger,
        "FEATURED IMAGE PREPARATION",
        (
            format_detail_line("Property ID", property_item.id, highlight=True),
            format_detail_line("Featured image URL", property_item.featured_image_url),
        ),
    ):
        downloaded_images, temp_primary_path = prepare_primary_image(
            property_item,
            property_dir,
            downloaded_images,
        )
    primary_selected_path: Path | None = None

    try:
        with LoggedProcess(
            logger,
            "GEMINI PHOTO ANALYSIS",
            (
                format_detail_line("Property ID", property_item.id, highlight=True),
                format_detail_line("Photos to select", photos_to_select, highlight=True),
                format_detail_line("Audit path", property_dir / GEMINI_SELECTION_AUDIT_FILENAME),
            ),
        ):
            selected_photo_paths = _select_photo_paths(
                property_item=property_item,
                property_dir=property_dir,
                raw_dir=raw_dir,
                temporary_selected_dir=temporary_selected_dir,
                downloaded_images=downloaded_images,
                temp_primary_path=temp_primary_path,
                photos_to_select=photos_to_select,
            )

        with LoggedProcess(
            logger,
            "SELECTED PHOTO SET PREPARATION",
            (
                format_detail_line("Property ID", property_item.id, highlight=True),
                format_detail_line("Selected directory", selected_dir),
            ),
        ):
            selected_dir.mkdir(parents=True, exist_ok=True)
            move_directory_contents(temporary_selected_dir, selected_dir)
            primary_selected_path = store_primary_image(
                property_item,
                selected_dir,
                temp_primary_path,
            )
            if primary_selected_path is not None:
                logger.info(
                    "%s",
                    format_detail_line("Stored featured image", primary_selected_path.name, highlight=True),
                )
        logger.info(
            "%s\n%s\n%s\n%s",
            format_detail_line("Photo selection summary", "Completed", highlight=True),
            format_detail_line("Property ID", property_item.id),
            format_detail_line("Selected photo count", len(selected_photo_paths), highlight=True),
            format_detail_line("Elapsed", f"{time.perf_counter() - started_at:.3f}s", highlight=True),
        )

        filtered_images = build_filtered_image_records(
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
        if should_cleanup_raw_property_dir(cleanup_temporary_files):
            cleanup_raw_property_dir(raw_property_dir)


__all__ = [
    "build_filtered_image_records",
    "build_selected_image_map",
    "download_and_filter_property_images",
    "prepare_primary_image",
    "store_primary_image",
]

