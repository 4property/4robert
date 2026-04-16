from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from services.reel_rendering.data import load_property_reel_data
from services.reel_rendering.formatting import (
    build_agent_lines,
    build_display_price,
    build_property_facts_line,
)
from services.reel_rendering.layout import build_overlay_layout
from services.reel_rendering.models import (
    PreparedReelAssets,
    PropertyRenderData,
    PropertyReelSlide,
    PropertyReelTemplate,
    property_reel_template_to_dict,
)
from services.reel_rendering.preparation import prepare_reel_render_assets
from services.reel_rendering.runtime import (
    compute_segment_timing,
    prepare_cover_logo_image,
    resolve_background_audio_paths,
    resolve_ber_icon_path,
    resolve_manifest_output_path,
    select_reel_slides,
    should_reserve_agency_logo_space,
)

logger = logging.getLogger(__name__)


def build_property_reel_manifest_from_data(
    base_dir: str | Path,
    property_data: PropertyRenderData,
    *,
    template: PropertyReelTemplate | None = None,
    render_profile: str | None = None,
    prepared_assets: PreparedReelAssets | None = None,
    working_dir: str | Path | None = None,
) -> dict[str, Any]:
    workspace_dir = Path(base_dir).expanduser().resolve()
    settings = template or PropertyReelTemplate()

    created_temp_dir = prepared_assets is None and working_dir is None
    temp_dir = (
        Path(working_dir).expanduser().resolve()
        if working_dir is not None
        else Path(tempfile.mkdtemp(prefix="reel_manifest_", dir=workspace_dir))
    )
    try:
        if prepared_assets is None and working_dir is not None:
            prepared_assets = prepare_reel_render_assets(
                workspace_dir,
                property_data,
                template=settings,
                working_dir=temp_dir,
            )

        if prepared_assets is None:
            slides = select_reel_slides(
                property_data,
                max_slide_count=settings.max_slide_count,
                temp_dir=temp_dir,
            )
        else:
            slides = [
                PropertyReelSlide(
                    image_path=prepared_slide.original_path,
                    caption=prepared_slide.caption,
                )
                for prepared_slide in prepared_assets.slides
            ]
    finally:
        if created_temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
    property_data.selected_slides = tuple(slides)
    slide_image_paths = [slide.image_path for slide in slides]
    ber_icon_path = resolve_ber_icon_path(
        workspace_dir,
        settings,
        property_data.ber_rating,
    )
    segment_frames, segment_durations, actual_total_duration = compute_segment_timing(
        settings,
        len(slide_image_paths),
    )
    slide_duration = (
        segment_durations[0]
        if segment_durations
        else 0.0
    )
    duration_delta = round(actual_total_duration - settings.total_duration_seconds, 3)
    if abs(duration_delta) > 0.001:
        logger.warning(
            "Configured reel duration %.3fs does not match actual duration %.3fs for %s (delta %.3fs).",
            settings.total_duration_seconds,
            actual_total_duration,
            property_data.slug,
            duration_delta,
        )
    cover_logo_path = prepare_cover_logo_image(workspace_dir, property_data, settings)
    reserve_agency_logo_space = (
        prepared_assets.reserve_agency_logo_space or prepared_assets.cover_logo_path is not None
        if prepared_assets is not None
        else should_reserve_agency_logo_space(
            property_data,
            cover_logo_path=cover_logo_path,
        )
    )
    overlay_layout = build_overlay_layout(
        property_data,
        settings,
        slides=tuple(slides),
        slide_duration=slide_duration,
        has_ber_badge=ber_icon_path is not None,
        has_agency_logo=reserve_agency_logo_space,
        cover_caption=slides[0].caption if settings.include_intro and slides else None,
    )
    has_intro_segment = settings.include_intro and settings.intro_duration_seconds > 0.0
    actual_intro_duration = settings.intro_duration_seconds if settings.include_intro else 0.0
    prepared_manifest: dict[str, Any] | None = None
    if prepared_assets is not None:
        prepared_manifest = {
            "working_dir": str(prepared_assets.working_dir),
            "segment_count": len(prepared_assets.slides) + (1 if has_intro_segment else 0),
            "slides": [
                {
                    "original_image_path": str(slide.original_path),
                    "working_image_path": str(slide.working_path),
                    "caption": slide.caption,
                    "working_resolution": [slide.working_width, slide.working_height],
                    "motion_mode": slide.motion_mode,
                    "source_resolution": (
                        [slide.source_width, slide.source_height]
                        if slide.source_width is not None and slide.source_height is not None
                        else None
                    ),
                }
                for slide in prepared_assets.slides
            ],
            "cover_background_path": str(prepared_assets.cover_background_path),
            "cover_logo_path": (
                str(prepared_assets.cover_logo_path)
                if prepared_assets.cover_logo_path is not None
                else None
            ),
            "agent_image_path": str(prepared_assets.agent_image_path),
            "ber_icon_path": (
                str(prepared_assets.ber_icon_path)
                if prepared_assets.ber_icon_path is not None
                else None
            ),
            "background_audio_path": str(prepared_assets.background_audio_path),
            "background_audio_candidates": [
                str(path) for path in prepared_assets.background_audio_candidates
            ],
        }

    background_audio_candidates = (
        prepared_assets.background_audio_candidates
        if prepared_assets is not None and prepared_assets.background_audio_candidates
        else resolve_background_audio_paths(
            workspace_dir,
            settings,
            shuffle_candidates=False,
        )
    )

    return {
        "site_id": property_data.site_id,
        "property_id": property_data.property_id,
        "render_profile": render_profile,
        "render_settings": property_reel_template_to_dict(settings),
        "slug": property_data.slug,
        "title": property_data.title,
        "link": property_data.link,
        "property_status": property_data.property_status,
        "listing_lifecycle": property_data.listing_lifecycle,
        "banner_text": property_data.banner_text,
        "viewing_times": list(property_data.viewing_times),
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
        "cover_logo_path": (
            str(cover_logo_path)
            if cover_logo_path is not None
            else None
        ),
        "background_audio_path": str(
            prepared_assets.background_audio_path
            if prepared_assets is not None
            else background_audio_candidates[0]
        ),
        "background_audio_candidates": [str(path) for path in background_audio_candidates],
        "estimated_duration_seconds": actual_total_duration,
        "configured_total_duration_seconds": settings.total_duration_seconds,
        "actual_total_duration_seconds": actual_total_duration,
        "duration_delta_seconds": duration_delta,
        "intro_duration_seconds": actual_intro_duration,
        "seconds_per_slide": settings.seconds_per_slide,
        "actual_segment_durations_seconds": segment_durations,
        "actual_segment_frame_counts": segment_frames,
        "slide_count": len(slide_image_paths),
        "segment_count": len(slide_image_paths) + (1 if has_intro_segment else 0),
        "fps": settings.fps,
        "resolution": [settings.width, settings.height],
        "property_facts": build_property_facts_line(property_data),
        "agent_lines": build_agent_lines(property_data),
        "price": build_display_price(property_data),
        "overlay_layout": overlay_layout.to_dict(),
        "prepared_assets": prepared_manifest,
    }


def write_property_reel_manifest_from_data(
    base_dir: str | Path,
    property_data: PropertyRenderData,
    *,
    output_path: str | Path | None = None,
    template: PropertyReelTemplate | None = None,
    render_profile: str | None = None,
    prepared_assets: PreparedReelAssets | None = None,
    working_dir: str | Path | None = None,
) -> Path:
    workspace_dir = Path(base_dir).expanduser().resolve()
    settings = template or PropertyReelTemplate()
    manifest = build_property_reel_manifest_from_data(
        workspace_dir,
        property_data,
        template=settings,
        render_profile=render_profile,
        prepared_assets=prepared_assets,
        working_dir=working_dir,
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
    site_id: str,
    property_id: int | None = None,
    slug: str | None = None,
    template: PropertyReelTemplate | None = None,
    render_profile: str | None = None,
    working_dir: str | Path | None = None,
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
        render_profile=render_profile,
        working_dir=working_dir,
    )


def write_property_reel_manifest(
    base_dir: str | Path,
    *,
    site_id: str,
    property_id: int | None = None,
    slug: str | None = None,
    output_path: str | Path | None = None,
    template: PropertyReelTemplate | None = None,
    render_profile: str | None = None,
    working_dir: str | Path | None = None,
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
        render_profile=render_profile,
        working_dir=working_dir,
    )


__all__ = [
    "build_property_reel_manifest",
    "build_property_reel_manifest_from_data",
    "write_property_reel_manifest",
    "write_property_reel_manifest_from_data",
]

