"""Rendering runtime slide selection and output path helpers."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from modules.rendering.infrastructure.ai_photo_selection.prompting import normalize_caption
from modules.rendering.infrastructure.models import (
    PRIMARY_IMAGE_NAME,
    PropertyRenderData,
    PropertyReelSlide,
    PropertyReelTemplate,
)
from modules.rendering.infrastructure.runtime.assets import download_primary_image
from shared.storage.site_layout import resolve_site_storage_layout
from settings import GEMINI_SELECTION_AUDIT_FILENAME
from settings.images import IMAGE_EXTENSIONS
from shared.errors import PropertyReelError

logger = logging.getLogger(__name__)


def sorted_image_paths(folder: Path) -> list[Path]:
    return sorted(
        candidate
        for candidate in folder.iterdir()
        if candidate.is_file() and candidate.suffix.lower() in IMAGE_EXTENSIONS
    )


def selection_audit_path(selected_image_dir: Path) -> Path:
    return selected_image_dir.parent / GEMINI_SELECTION_AUDIT_FILENAME


def strip_selected_prefix(filename: str) -> str:
    return re.sub(r"^\d+_", "", filename)


def load_selected_image_rows(selected_image_dir: Path) -> list[dict[str, object]]:
    audit_path = selection_audit_path(selected_image_dir)
    if not audit_path.exists():
        return []

    try:
        payload = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read Gemini selection audit at %s: %s", audit_path, exc)
        return []

    rows = payload.get("selected_images")
    if not isinstance(rows, list):
        logger.warning(
            "Gemini selection audit at %s does not contain a valid selected_images list.",
            audit_path,
        )
        return []

    return [row for row in rows if isinstance(row, dict)]


def row_caption(row: dict[str, object] | None) -> str | None:
    if row is None:
        return None
    caption = row.get("caption")
    if not isinstance(caption, str):
        return None
    cleaned = normalize_caption(caption, "").strip()
    return cleaned or None


def match_selected_row(
    image_path: Path,
    *,
    rows_by_exact: dict[str, dict[str, object]],
    rows_by_normalized: dict[str, dict[str, object]],
    reserved_row: dict[str, object] | None,
) -> dict[str, object] | None:
    if image_path.stem.lower() == PRIMARY_IMAGE_NAME:
        return reserved_row or rows_by_exact.get(image_path.name)

    normalized_name = strip_selected_prefix(image_path.name)
    normalized_stem = strip_selected_prefix(image_path.stem)
    return (
        rows_by_exact.get(image_path.name)
        or rows_by_exact.get(normalized_name)
        or rows_by_normalized.get(image_path.name)
        or rows_by_normalized.get(normalized_name)
        or rows_by_normalized.get(f"{normalized_stem}{image_path.suffix}")
    )


def build_local_selected_slides(
    selected_image_dir: Path,
    selected_image_paths: tuple[Path, ...] = (),
) -> tuple[PropertyReelSlide, ...]:
    if selected_image_paths:
        image_paths = selected_image_paths
    elif selected_image_dir.exists():
        image_paths = tuple(sorted_image_paths(selected_image_dir))
    else:
        image_paths = ()
    if not image_paths:
        return ()

    rows = load_selected_image_rows(selected_image_dir)
    reserved_row = next((row for row in rows if row.get("reserved") is True), None)
    rows_by_exact = {
        str(row["file"]).strip(): row
        for row in rows
        if str(row.get("file", "")).strip()
    }
    rows_by_normalized = {
        strip_selected_prefix(file_name): row
        for file_name, row in rows_by_exact.items()
    }

    slides: list[PropertyReelSlide] = []
    for image_path in image_paths:
        matched_row = match_selected_row(
            image_path,
            rows_by_exact=rows_by_exact,
            rows_by_normalized=rows_by_normalized,
            reserved_row=reserved_row,
        )
        if matched_row is None and rows:
            logger.warning("No Gemini caption match found for %s.", image_path.name)
        slides.append(PropertyReelSlide(image_path=image_path, caption=row_caption(matched_row)))
    return tuple(slides)


def select_reel_slides(
    property_data: PropertyRenderData,
    *,
    max_slide_count: int,
    temp_dir: Path,
) -> list[PropertyReelSlide]:
    slides = list(property_data.selected_slides) or list(
        build_local_selected_slides(
            property_data.selected_image_dir,
            property_data.selected_image_paths,
        )
    )
    reserved_row = next(
        (
            row
            for row in load_selected_image_rows(property_data.selected_image_dir)
            if row.get("reserved") is True
        ),
        None,
    )
    primary_slide = next(
        (
            slide
            for slide in slides
            if slide.image_path.stem.lower() == PRIMARY_IMAGE_NAME
        ),
        None,
    )

    if primary_slide is None and property_data.featured_image_url:
        suffix = Path(property_data.featured_image_url).suffix or ".jpg"
        primary_image_path = download_primary_image(
            property_data.featured_image_url,
            temp_dir / f"{PRIMARY_IMAGE_NAME}{suffix.lower()}",
        )
        primary_slide = PropertyReelSlide(
            image_path=primary_image_path,
            caption=row_caption(reserved_row),
        )

    ordered_slides: list[PropertyReelSlide] = []
    if primary_slide is not None:
        ordered_slides.append(primary_slide)

    ordered_slides.extend(
        slide
        for slide in slides
        if primary_slide is None
        or slide.image_path.resolve() != primary_slide.image_path.resolve()
    )

    if not ordered_slides:
        raise PropertyReelError(
            "No local images are available for reel generation.",
            context={
                "site_id": property_data.site_id,
                "property_id": property_data.property_id,
                "selected_image_dir": str(property_data.selected_image_dir),
            },
            hint=(
                "Run the asset preparation stage first and verify the selected_photos "
                "directory is persisted on the deployed host."
            ),
        )

    return ordered_slides[:max_slide_count]


def select_reel_images(
    property_data: PropertyRenderData,
    *,
    max_slide_count: int,
    temp_dir: Path,
) -> list[Path]:
    return [
        slide.image_path
        for slide in select_reel_slides(
            property_data,
            max_slide_count=max_slide_count,
            temp_dir=temp_dir,
        )
    ]


def resolve_reel_output_path(
    workspace_dir: Path,
    property_data: PropertyRenderData,
    settings: PropertyReelTemplate,
    output_path: str | Path | None,
) -> Path:
    del settings
    output_dir = resolve_site_storage_layout(
        workspace_dir,
        property_data.site_id,
    ).generated_reels_root
    output_dir.mkdir(parents=True, exist_ok=True)
    final_output_path = (
        Path(output_path).expanduser().resolve()
        if output_path is not None
        else output_dir / f"{property_data.slug}-reel.mp4"
    )
    final_output_path.parent.mkdir(parents=True, exist_ok=True)
    return final_output_path


def resolve_manifest_output_path(
    workspace_dir: Path,
    site_id: str,
    slug: str,
    settings: PropertyReelTemplate,
    output_path: str | Path | None,
) -> Path:
    del settings
    storage_paths = resolve_site_storage_layout(workspace_dir, site_id)
    manifest_path = (
        Path(output_path).expanduser().resolve()
        if output_path is not None
        else storage_paths.generated_reels_root / f"{slug}-reel.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    return manifest_path


def compute_slide_timing(
    settings: PropertyReelTemplate,
    slide_count: int,
) -> tuple[int, float, float]:
    segment_frames, segment_durations, total_duration = compute_segment_timing(
        settings,
        slide_count,
    )
    if not segment_frames or not segment_durations:
        return 0, 0.0, total_duration
    return segment_frames[0], segment_durations[0], total_duration


def compute_segment_timing(
    settings: PropertyReelTemplate,
    slide_count: int,
) -> tuple[list[int], list[float], float]:
    if slide_count <= 0:
        intro_duration = settings.intro_duration_seconds if settings.include_intro else 0.0
        return [], [], intro_duration

    slide_frames = max(1, round(settings.seconds_per_slide * settings.fps))
    segment_frames = [slide_frames for _ in range(slide_count)]
    intro_duration = settings.intro_duration_seconds if settings.include_intro else 0.0
    if slide_count >= settings.max_slide_count:
        available_duration = max(settings.total_duration_seconds - intro_duration, 0.0)
        target_total_frames = max(slide_count, round(available_duration * settings.fps))
        base_frames, remainder = divmod(target_total_frames, slide_count)
        base_frames = max(base_frames, 1)
        segment_frames = [
            base_frames + (1 if index < remainder else 0)
            for index in range(slide_count)
        ]

    segment_durations = [frame_count / settings.fps for frame_count in segment_frames]
    total_duration = intro_duration + sum(segment_durations)
    return segment_frames, segment_durations, total_duration


def compute_audio_fade(total_duration: float) -> tuple[float, float]:
    audio_fade_duration = min(1.5, total_duration)
    audio_fade_start = max(total_duration - audio_fade_duration, 0.0)
    return audio_fade_duration, audio_fade_start


__all__ = [
    "build_local_selected_slides",
    "compute_audio_fade",
    "compute_segment_timing",
    "compute_slide_timing",
    "load_selected_image_rows",
    "match_selected_row",
    "resolve_manifest_output_path",
    "resolve_reel_output_path",
    "row_caption",
    "select_reel_images",
    "select_reel_slides",
    "selection_audit_path",
    "sorted_image_paths",
    "strip_selected_prefix",
]
