from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from config import LEGACY_SITE_ID
from services.reel_rendering.data import load_property_reel_data
from services.reel_rendering.formatting import build_agent_lines, build_property_facts_line, format_price
from services.reel_rendering.models import PropertyRenderData, PropertyReelTemplate
from services.reel_rendering.runtime import (
    compute_slide_timing,
    resolve_ber_icon_path,
    resolve_asset_path,
    resolve_manifest_output_path,
    select_reel_slides,
)

logger = logging.getLogger(__name__)


def build_property_reel_manifest_from_data(
    base_dir: str | Path,
    property_data: PropertyRenderData,
    *,
    template: PropertyReelTemplate | None = None,
) -> dict[str, Any]:
    workspace_dir = Path(base_dir).expanduser().resolve()
    settings = template or PropertyReelTemplate()

    temp_dir = Path(tempfile.mkdtemp(prefix="reel_manifest_", dir=workspace_dir))
    try:
        slides = select_reel_slides(
            property_data,
            max_slide_count=settings.max_slide_count,
            temp_dir=temp_dir,
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    property_data.selected_slides = tuple(slides)
    slide_image_paths = [slide.image_path for slide in slides]
    ber_icon_path = resolve_ber_icon_path(
        workspace_dir,
        settings,
        property_data.ber_rating,
    )
    _, _, actual_total_duration = compute_slide_timing(settings, len(slide_image_paths))
    duration_delta = round(actual_total_duration - settings.total_duration_seconds, 3)
    if abs(duration_delta) > 0.001:
        logger.warning(
            "Configured reel duration %.3fs does not match actual duration %.3fs for %s (delta %.3fs).",
            settings.total_duration_seconds,
            actual_total_duration,
            property_data.slug,
            duration_delta,
        )

    return {
        "site_id": property_data.site_id,
        "property_id": property_data.property_id,
        "slug": property_data.slug,
        "title": property_data.title,
        "link": property_data.link,
        "property_status": property_data.property_status,
        "featured_image_url": property_data.featured_image_url,
        "agent_photo_url": property_data.agent_photo_url,
        "ber_rating": property_data.ber_rating,
        "ber_icon_path": None if ber_icon_path is None else str(ber_icon_path),
        "slide_image_paths": [str(path) for path in slide_image_paths],
        "slides": [
            {
                "image_path": str(slide.image_path),
                "caption": slide.caption,
            }
            for slide in slides
        ],
        "cover_logo_path": str(
            resolve_asset_path(workspace_dir, settings, settings.cover_logo_filename)
        ),
        "background_audio_path": str(
            resolve_asset_path(workspace_dir, settings, settings.background_audio_filename)
        ),
        "estimated_duration_seconds": actual_total_duration,
        "configured_total_duration_seconds": settings.total_duration_seconds,
        "actual_total_duration_seconds": actual_total_duration,
        "duration_delta_seconds": duration_delta,
        "intro_duration_seconds": settings.intro_duration_seconds,
        "seconds_per_slide": settings.seconds_per_slide,
        "slide_count": len(slide_image_paths),
        "fps": settings.fps,
        "resolution": [settings.width, settings.height],
        "property_facts": build_property_facts_line(property_data),
        "agent_lines": build_agent_lines(property_data),
        "price": format_price(property_data.price),
    }


def write_property_reel_manifest_from_data(
    base_dir: str | Path,
    property_data: PropertyRenderData,
    *,
    output_path: str | Path | None = None,
    template: PropertyReelTemplate | None = None,
) -> Path:
    workspace_dir = Path(base_dir).expanduser().resolve()
    settings = template or PropertyReelTemplate()
    manifest = build_property_reel_manifest_from_data(
        workspace_dir,
        property_data,
        template=settings,
    )
    manifest_path = resolve_manifest_output_path(
        workspace_dir,
        property_data.site_id,
        property_data.slug,
        settings,
        output_path,
    )
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def build_property_reel_manifest(
    base_dir: str | Path,
    *,
    site_id: str = LEGACY_SITE_ID,
    property_id: int | None = None,
    slug: str | None = None,
    template: PropertyReelTemplate | None = None,
) -> dict[str, Any]:
    workspace_dir = Path(base_dir).expanduser().resolve()
    property_data = load_property_reel_data(
        workspace_dir,
        site_id=site_id,
        property_id=property_id,
        slug=slug,
    )
    return build_property_reel_manifest_from_data(
        workspace_dir,
        property_data,
        template=template,
    )


def write_property_reel_manifest(
    base_dir: str | Path,
    *,
    site_id: str = LEGACY_SITE_ID,
    property_id: int | None = None,
    slug: str | None = None,
    output_path: str | Path | None = None,
    template: PropertyReelTemplate | None = None,
) -> Path:
    workspace_dir = Path(base_dir).expanduser().resolve()
    property_data = load_property_reel_data(
        workspace_dir,
        site_id=site_id,
        property_id=property_id,
        slug=slug,
    )
    return write_property_reel_manifest_from_data(
        workspace_dir,
        property_data,
        output_path=output_path,
        template=template,
    )


__all__ = [
    "build_property_reel_manifest",
    "build_property_reel_manifest_from_data",
    "write_property_reel_manifest",
    "write_property_reel_manifest_from_data",
]

