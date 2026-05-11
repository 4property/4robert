"""Pure frame composition for property reels (step 3 of the legacy pipeline).

Orchestrates the low-level rendering primitives in
``services.media.reel_rendering.*`` (and indirectly the modern
``modules.rendering.infrastructure.*`` runtime) to produce a
``RenderedMediaArtifact`` for a ``PropertyContext`` plus prepared
``PreparedMediaAssets``. No DB access, no HTTP, no outbox: pure compute
plus filesystem writes inside a per-reel staging directory.

Replaces the body of ``DefaultMediaRenderer`` from the now-deleted
``application/pipeline/media_services.py``. The bridge
``application/bootstrap/pipeline_adapters`` keeps the four thin
adapters (``DefaultPropertyInfoService``, ``DefaultMediaPreparationService``,
``FileSystemMediaPublisher``, ``CompositeMediaPublisher``); the renderer
moved here because it is the only piece of pure compute left and it
belongs to the rendering bounded context.

The class name ``DefaultMediaRenderer`` is preserved verbatim to satisfy
the legacy ``MediaRenderer`` Protocol in
``application/pipeline/interfaces.py`` without forcing changes to
``application/pipeline/media_pipeline.py``. Feature 16 retires the
class entirely when it replaces ``PropertyMediaPipeline``.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from uuid import uuid4

from modules.reels.domain.types import (
    PreparedMediaAssets,
    PropertyContext,
    RenderedMediaArtifact,
)
from shared.observability import format_console_block, format_detail_line
from modules.rendering.infrastructure.ffmpeg import (
    build_reel_template_for_render_profile,
    generate_property_reel_from_data,
)
from modules.rendering.infrastructure.manifest import write_property_reel_manifest_from_data
from modules.rendering.infrastructure.models import PropertyRenderData
from modules.rendering.infrastructure.poster import generate_property_poster_from_data
from modules.rendering.infrastructure.preparation import prepare_reel_render_assets
from modules.rendering.infrastructure.runtime import build_local_selected_slides

logger = logging.getLogger(__name__)


class DefaultMediaRenderer:
    def __init__(self, workspace_dir: str | Path) -> None:
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()

    def render_media(
        self,
        context: PropertyContext,
        prepared_assets: PreparedMediaAssets,
    ) -> RenderedMediaArtifact:
        return self._render_reel(context, prepared_assets)

    def render_video(
        self,
        context: PropertyContext,
        selected_photos: PreparedMediaAssets,
    ) -> RenderedMediaArtifact:
        return self.render_media(context, selected_photos)

    def _render_reel(
        self,
        context: PropertyContext,
        prepared_assets: PreparedMediaAssets,
    ) -> RenderedMediaArtifact:
        revision_id = uuid4().hex
        template = build_reel_template_for_render_profile(context.delivery_plan.render_profile)
        staging_root = context.storage_paths.generated_reels_root / "_staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(
            tempfile.mkdtemp(prefix=f"{context.property.slug}-", dir=staging_root)
        )
        manifest_path = staging_dir / f"{context.property.slug}-reel.json"
        media_path = staging_dir / f"{context.property.slug}-reel.mp4"
        poster_path = staging_dir / f"{context.property.slug}-poster.jpg"
        selected_slides = build_local_selected_slides(
            prepared_assets.selected_dir,
            prepared_assets.selected_photo_paths,
        )
        property_render_data = self._build_render_data(
            context=context,
            prepared_assets=prepared_assets,
            selected_slides=selected_slides,
        )
        render_working_dir = staging_dir / "_prepared"
        prepared_render_assets = prepare_reel_render_assets(
            self.workspace_dir,
            property_render_data,
            template=template,
            working_dir=render_working_dir,
        )

        write_property_reel_manifest_from_data(
            self.workspace_dir,
            property_render_data,
            output_path=manifest_path,
            template=template,
            render_profile=context.delivery_plan.render_profile,
            prepared_assets=prepared_render_assets,
            working_dir=render_working_dir,
        )
        generate_property_reel_from_data(
            self.workspace_dir,
            property_render_data,
            output_path=media_path,
            template=template,
            prepared_assets=prepared_render_assets,
            working_dir=render_working_dir,
        )
        generate_property_poster_from_data(
            self.workspace_dir,
            property_render_data,
            output_path=poster_path,
        )
        logger.info(
            format_console_block(
                "Reel Render Completed",
                format_detail_line("Site ID", context.site_id),
                format_detail_line("Property ID", context.property.id),
                format_detail_line("Render profile", context.delivery_plan.render_profile),
                format_detail_line("Revision ID", revision_id),
                format_detail_line("Staging directory", staging_dir),
                format_detail_line("Manifest path", manifest_path),
                format_detail_line("Media path", media_path),
                format_detail_line("Poster path", poster_path),
            )
        )
        return RenderedMediaArtifact(
            staging_dir=staging_dir,
            artifact_kind="reel_video",
            media_path=media_path,
            metadata_path=manifest_path,
            revision_id=revision_id,
        )

    @staticmethod
    def _build_render_data(
        *,
        context: PropertyContext,
        prepared_assets: PreparedMediaAssets,
        selected_slides,
    ) -> PropertyRenderData:
        return PropertyRenderData(
            site_id=context.site_id,
            property_id=context.property.id,
            slug=context.property.slug,
            title=context.property.title or context.property.slug,
            link=context.property.link,
            property_status=context.property.property_status,
            listing_lifecycle=context.delivery_plan.listing_lifecycle,
            banner_text=context.delivery_plan.banner_text,
            selected_image_dir=prepared_assets.selected_dir,
            selected_image_paths=prepared_assets.selected_photo_paths,
            featured_image_url=context.property.featured_image_url,
            bedrooms=context.property.bedrooms,
            bathrooms=context.property.bathrooms,
            ber_rating=context.property.ber_rating,
            agent_name=context.property.agent_name,
            agent_photo_url=context.property.agent_photo_url,
            agent_email=context.property.agent_email,
            agent_mobile=context.property.agent_mobile,
            agent_number=context.property.agent_number,
            agency_psra=context.property.agency_psra,
            agency_logo_url=context.property.agency_logo_url,
            price=context.property.price,
            price_display_text=context.delivery_plan.price_display_text,
            property_type_label=context.property.property_type_label,
            property_area_label=context.property.property_area_label,
            property_county_label=context.property.property_county_label,
            eircode=context.property.eircode,
            property_size=context.property.property_size,
            selected_slides=tuple(selected_slides),
        )


__all__ = ["DefaultMediaRenderer"]
