from __future__ import annotations

import logging
import shutil
from pathlib import Path
from urllib.request import urlopen

from config import OUTBOUND_HTTP_TIMEOUT_SECONDS
from core.logging import create_progress, format_detail_line, format_message_line
from models.property import Property
from repositories.property_pipeline_repository import DownloadedImage
from services.property_media.filesystem import cleanup_raw_property_dir, prepare_property_directories
from services.property_media.naming import build_image_filename, build_request

logger = logging.getLogger(__name__)


def download_image(image_url: str, destination: Path) -> None:
    with urlopen(build_request(image_url), timeout=OUTBOUND_HTTP_TIMEOUT_SECONDS) as response:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as file_handle:
            shutil.copyfileobj(response, file_handle)


def download_images_to_directory(
    property_item: Property,
    destination_dir: Path,
    *,
    overwrite_existing: bool,
    show_progress: bool,
) -> list[DownloadedImage]:
    downloaded_images: list[DownloadedImage] = []
    total_images = len(property_item.image_urls)

    with create_progress(transient=False) as progress:
        task_id = progress.add_task(
            f"DOWNLOADING RAW IMAGES FOR PROPERTY {property_item.id}",
            total=total_images,
        )
        for position, image_url in enumerate(property_item.image_urls, start=1):
            filename = build_image_filename(position, image_url)
            destination = destination_dir / filename

            progress.update(
                task_id,
                description=f"DOWNLOADING RAW IMAGES FOR PROPERTY {property_item.id} [{position}/{total_images}]",
            )
            try:
                if show_progress:
                    logger.info(
                        "%s\n%s\n%s\n%s",
                        format_message_line("Downloading property image", tone="progress"),
                        format_detail_line("Property ID", property_item.id),
                        format_detail_line("Image", f"{position}/{total_images}", highlight=True),
                        format_detail_line("Source URL", image_url),
                    )
                if overwrite_existing or not destination.exists() or destination.stat().st_size == 0:
                    download_image(image_url, destination)
                downloaded_images.append((position, image_url, destination))
                if show_progress:
                    logger.info(
                        "%s\n%s",
                        format_message_line("Image download completed", tone="success"),
                        format_detail_line("Saved path", destination),
                    )
            except Exception as exc:
                logger.warning(
                    "%s\n%s\n%s\n%s",
                    format_message_line("Image download failed", tone="failure"),
                    format_detail_line("Property ID", property_item.id),
                    format_detail_line("Source URL", image_url),
                    format_detail_line("Error", exc, highlight=True),
                )
                downloaded_images.append((position, image_url, None))
            finally:
                progress.advance(task_id)

    return downloaded_images


def has_downloaded_images(downloaded_images: list[DownloadedImage]) -> bool:
    return any(local_path is not None for _, _, local_path in downloaded_images)


def download_property_images(
    property_item: Property,
    raw_images_root: Path,
) -> tuple[Path, list[DownloadedImage]]:
    _, raw_property_dir, raw_dir, _ = prepare_property_directories(
        raw_images_root,
        raw_images_root,
        property_item,
        clear_selected_dir=False,
    )

    downloads = download_images_to_directory(
        property_item,
        raw_dir,
        overwrite_existing=False,
        show_progress=False,
    )

    if not has_downloaded_images(downloads):
        cleanup_raw_property_dir(raw_property_dir)

    return raw_dir, downloads


__all__ = ["download_image", "download_images_to_directory", "download_property_images", "has_downloaded_images"]

