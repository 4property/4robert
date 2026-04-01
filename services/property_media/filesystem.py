from __future__ import annotations

import shutil
from pathlib import Path

from config import IMAGE_EXTENSIONS, RAW_PHOTOS_DIRNAME, SELECTED_PHOTOS_DIRNAME
from models.property import Property


def prepare_property_directories(
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


def cleanup_raw_property_dir(raw_property_dir: Path) -> None:
    shutil.rmtree(raw_property_dir, ignore_errors=True)


def list_image_files(folder: Path) -> list[Path]:
    return sorted(
        candidate
        for candidate in folder.iterdir()
        if candidate.is_file() and candidate.suffix.lower() in IMAGE_EXTENSIONS
    )


def move_directory_contents(source_dir: Path, destination_dir: Path) -> None:
    if not source_dir.exists():
        return

    destination_dir.mkdir(parents=True, exist_ok=True)
    for source_path in sorted(source_dir.iterdir()):
        shutil.move(str(source_path), destination_dir / source_path.name)

    source_dir.rmdir()


__all__ = [
    "cleanup_raw_property_dir",
    "list_image_files",
    "move_directory_contents",
    "prepare_property_directories",
]
