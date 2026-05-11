"""Scripted video render service.

Moved from ``application/scripted_render/service.py`` during sub-feature 18b.
The validation and coercion helpers live next to it in
``payload_helpers.py``; sub-feature 18c migrated the rendering primitives
out of ``services/media/reel_rendering/`` into
``modules.rendering.infrastructure``.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from modules.catalog.domain.wordpress_property import Property
from modules.reels.domain.media_planning import build_media_delivery_plan
from modules.rendering.infrastructure.ffmpeg import (
    build_reel_template_for_render_profile,
    generate_property_reel_from_data,
)
from modules.rendering.infrastructure.manifest import write_property_reel_manifest_from_data
from modules.rendering.infrastructure.models import (
    PropertyRenderData,
    PropertyReelTemplate,
)
from modules.rendering.infrastructure.preparation import prepare_reel_render_assets
from shared.errors import ApplicationError, ResourceNotFoundError, ValidationError
from shared.storage.site_layout import resolve_site_storage_layout

from .payload_helpers import (
    ScriptedVideoArtifactRecord,
    ScriptedVideoRenderResult,
    UnitOfWork,
    optional_int,
    optional_text,
    optional_text_allow_blank,
    relative_path_text,
    replace_atomically,
    require_int,
    require_text,
    resolve_local_file_path,
    resolve_scripted_render_template,
    resolve_slides,
)


@dataclass(frozen=True, slots=True)
class _ResolvedScriptedVideoRequest:
    site_id: str
    source_property_id: int
    property_slug: str
    render_profile: str
    request_manifest_json: str
    property_data: PropertyRenderData
    template: PropertyReelTemplate
    background_audio_path: Path | None


class ScriptedVideoRenderService:
    def __init__(
        self,
        workspace_dir: str | Path,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
    ) -> None:
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.unit_of_work_factory = unit_of_work_factory

    def render_from_manifest(self, payload: Mapping[str, object]) -> ScriptedVideoRenderResult:
        if not isinstance(payload, Mapping):
            raise ValidationError(
                "Scripted render payload must be a JSON object.",
                code="INVALID_SCRIPTED_RENDER_PAYLOAD",
                hint="Send a JSON object whose fields describe the reel header and ordered slides.",
            )

        site_id = require_text(payload, "site_id")
        source_property_id = require_int(payload, "source_property_id")

        with self.unit_of_work_factory() as unit_of_work:
            source = unit_of_work.wordpress_source_store.get_by_site_id(site_id)
            if source is None or source.status != "active":
                raise ResourceNotFoundError(
                    "The referenced site is not provisioned.",
                    code="UNKNOWN_WORDPRESS_SITE",
                    context={"site_id": site_id},
                    hint="Provision an active wordpress_sources row for this site before retrying the scripted render.",
                )
            property_record = unit_of_work.property_repository.get_property_reel_record(
                site_id=site_id,
                property_id=source_property_id,
            )
        if property_record is None:
            raise ResourceNotFoundError(
                "The referenced property does not exist.",
                code="PROPERTY_NOT_FOUND",
                context={
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                },
                hint="Create or ingest the property first, then retry the scripted render.",
            )

        render_id = uuid4().hex
        resolved_request = self._resolve_request(
            payload=payload,
            property_slug=property_record.slug,
            source_property_id=source_property_id,
            site_id=site_id,
        )
        storage_paths = resolve_site_storage_layout(self.workspace_dir, site_id)
        staging_root = storage_paths.scripted_videos_root / "_staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        staging_dir = staging_root / f"{property_record.slug}-{render_id}"
        staging_dir.mkdir(parents=True, exist_ok=False)
        final_dir = storage_paths.scripted_videos_root / property_record.slug / render_id
        final_video_path = final_dir / "video.mp4"
        final_manifest_path = final_dir / "resolved-manifest.json"
        final_request_manifest_path = final_dir / "request-manifest.json"
        render_profile = resolved_request.render_profile

        request_manifest_path = staging_dir / "request-manifest.json"
        resolved_manifest_path = staging_dir / "resolved-manifest.json"
        media_path = staging_dir / "video.mp4"

        try:
            request_manifest_path.write_text(
                resolved_request.request_manifest_json,
                encoding="utf-8",
            )
            render_working_dir = staging_dir / "_prepared"
            template = resolved_request.template
            prepared_assets = prepare_reel_render_assets(
                self.workspace_dir,
                resolved_request.property_data,
                template=template,
                working_dir=render_working_dir,
            )
            if resolved_request.background_audio_path is not None:
                prepared_assets.background_audio_path = resolved_request.background_audio_path
                prepared_assets.background_audio_candidates = (resolved_request.background_audio_path,)

            write_property_reel_manifest_from_data(
                self.workspace_dir,
                resolved_request.property_data,
                output_path=resolved_manifest_path,
                template=template,
                render_profile=render_profile,
                prepared_assets=prepared_assets,
                working_dir=render_working_dir,
            )
            generate_property_reel_from_data(
                self.workspace_dir,
                resolved_request.property_data,
                output_path=media_path,
                template=template,
                prepared_assets=prepared_assets,
                working_dir=render_working_dir,
            )

            final_dir.mkdir(parents=True, exist_ok=True)
            replace_atomically(request_manifest_path, final_request_manifest_path)
            replace_atomically(resolved_manifest_path, final_manifest_path)
            replace_atomically(media_path, final_video_path)
            self._save_artifact(
                ScriptedVideoArtifactRecord(
                    render_id=render_id,
                    agency_id=source.agency_id,
                    wordpress_source_id=source.wordpress_source_id,
                    site_id=site_id,
                    source_property_id=source_property_id,
                    property_slug=property_record.slug,
                    render_profile=render_profile,
                    status="rendered",
                    request_manifest_json=resolved_request.request_manifest_json,
                    request_manifest_path=relative_path_text(self.workspace_dir, final_request_manifest_path),
                    resolved_manifest_path=relative_path_text(self.workspace_dir, final_manifest_path),
                    media_path=relative_path_text(self.workspace_dir, final_video_path),
                    error_message="",
                    created_at="",
                    updated_at="",
                )
            )
            return ScriptedVideoRenderResult(
                render_id=render_id,
                site_id=site_id,
                source_property_id=source_property_id,
                video_path=relative_path_text(self.workspace_dir, final_video_path),
                manifest_path=relative_path_text(self.workspace_dir, final_manifest_path),
                request_manifest_path=relative_path_text(self.workspace_dir, final_request_manifest_path),
            )
        except ApplicationError as error:
            shutil.rmtree(final_dir, ignore_errors=True)
            self._save_artifact(
                ScriptedVideoArtifactRecord(
                    render_id=render_id,
                    agency_id=source.agency_id,
                    wordpress_source_id=source.wordpress_source_id,
                    site_id=site_id,
                    source_property_id=source_property_id,
                    property_slug=property_record.slug,
                    render_profile=render_profile,
                    status="failed",
                    request_manifest_json=resolved_request.request_manifest_json,
                    request_manifest_path="",
                    resolved_manifest_path="",
                    media_path="",
                    error_message=str(error),
                    created_at="",
                    updated_at="",
                )
            )
            raise
        except Exception as error:
            shutil.rmtree(final_dir, ignore_errors=True)
            wrapped_error = ApplicationError(
                "Failed to render the scripted video.",
                context={
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                    "render_id": render_id,
                },
                hint="Check the render inputs and the staged output directory, then retry the request.",
                cause=error,
            )
            self._save_artifact(
                ScriptedVideoArtifactRecord(
                    render_id=render_id,
                    agency_id=source.agency_id,
                    wordpress_source_id=source.wordpress_source_id,
                    site_id=site_id,
                    source_property_id=source_property_id,
                    property_slug=property_record.slug,
                    render_profile=render_profile,
                    status="failed",
                    request_manifest_json=resolved_request.request_manifest_json,
                    request_manifest_path="",
                    resolved_manifest_path="",
                    media_path="",
                    error_message=str(wrapped_error),
                    created_at="",
                    updated_at="",
                )
            )
            raise wrapped_error from error
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    def _save_artifact(self, record: ScriptedVideoArtifactRecord) -> None:
        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.scripted_video_store.save_artifact(record)

    def _resolve_request(
        self,
        *,
        payload: Mapping[str, object],
        property_slug: str,
        source_property_id: int,
        site_id: str,
    ) -> _ResolvedScriptedVideoRequest:
        title = require_text(payload, "title")
        property_status = require_text(payload, "property_status")
        slides = resolve_slides(payload, workspace_dir=self.workspace_dir)
        request_manifest_json = json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True)

        defaults_property = Property(
            id=source_property_id,
            slug=property_slug,
            property_status=property_status,
            price=optional_text(payload, "price"),
            price_term=optional_text(payload, "price_term"),
        )
        delivery_plan = build_media_delivery_plan(defaults_property)

        render_profile = optional_text(payload, "render_profile") or delivery_plan.render_profile
        template = build_reel_template_for_render_profile(
            render_profile,
            template=resolve_scripted_render_template(payload),
        )
        listing_lifecycle = optional_text(payload, "listing_lifecycle") or delivery_plan.listing_lifecycle
        banner_text = (
            optional_text_allow_blank(payload, "banner_text")
            if "banner_text" in payload
            else delivery_plan.banner_text
        )
        price_display_text = (
            optional_text_allow_blank(payload, "price_display_text")
            if "price_display_text" in payload
            else delivery_plan.price_display_text
        )
        background_audio_path = None
        if "background_audio_path" in payload:
            background_audio_path = resolve_local_file_path(
                payload.get("background_audio_path"),
                workspace_dir=self.workspace_dir,
                code="INVALID_BACKGROUND_AUDIO_PATH",
                field_name="background_audio_path",
                hint="Use a readable local audio file path inside the workspace.",
            )

        property_data = PropertyRenderData(
            site_id=site_id,
            property_id=source_property_id,
            slug=property_slug,
            title=title,
            link=optional_text(payload, "link"),
            property_status=property_status,
            selected_image_dir=self.workspace_dir,
            selected_image_paths=tuple(slide.image_path for slide in slides),
            featured_image_url=optional_text(payload, "featured_image_url"),
            bedrooms=optional_int(payload, "bedrooms"),
            bathrooms=optional_int(payload, "bathrooms"),
            ber_rating=optional_text(payload, "ber_rating"),
            agent_name=optional_text(payload, "agent_name"),
            agent_photo_url=optional_text(payload, "agent_photo_url"),
            agent_email=optional_text(payload, "agent_email"),
            agent_mobile=optional_text(payload, "agent_mobile"),
            agent_number=optional_text(payload, "agent_number"),
            price=optional_text(payload, "price"),
            property_type_label=optional_text(payload, "property_type_label"),
            property_area_label=optional_text(payload, "property_area_label"),
            property_county_label=optional_text(payload, "property_county_label"),
            eircode=optional_text(payload, "eircode"),
            selected_slides=tuple(slides),
            property_size=optional_text(payload, "property_size"),
            agency_psra=optional_text(payload, "agency_psra"),
            agency_logo_url=optional_text(payload, "agency_logo_url"),
            listing_lifecycle=listing_lifecycle,
            banner_text=banner_text,
            price_display_text=price_display_text,
        )
        return _ResolvedScriptedVideoRequest(
            site_id=site_id,
            source_property_id=source_property_id,
            property_slug=property_slug,
            render_profile=render_profile,
            request_manifest_json=request_manifest_json,
            property_data=property_data,
            template=template,
            background_audio_path=background_audio_path,
        )


__all__ = [
    "ScriptedVideoRenderResult",
    "ScriptedVideoRenderService",
]
