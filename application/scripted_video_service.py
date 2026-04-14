from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError as PydanticValidationError

from application.media_planning import build_media_delivery_plan
from application.persistence import UnitOfWork
from core.errors import ApplicationError, ResourceNotFoundError, ValidationError
from models.property import Property
from repositories.scripted_video_artifact_repository import ScriptedVideoArtifactRecord
from services.reel_rendering import (
    PropertyRenderData,
    PropertyReelSlide,
    PropertyReelTemplate,
    build_reel_template_for_render_profile,
    generate_property_reel_from_data,
    write_property_reel_manifest_from_data,
)
from services.reel_rendering.preparation import prepare_reel_render_assets
from services.webhook_transport.site_storage import resolve_site_storage_layout


@dataclass(frozen=True, slots=True)
class ScriptedVideoRenderResult:
    render_id: str
    site_id: str
    source_property_id: int
    video_path: str
    manifest_path: str
    request_manifest_path: str


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


class _ScriptedRenderSettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    width: int | None = Field(default=None, ge=2)
    height: int | None = Field(default=None, ge=2)
    fps: int | None = Field(default=None, ge=1)
    total_duration_seconds: float | None = Field(default=None, gt=0.0)
    seconds_per_slide: float | None = Field(default=None, gt=0.0)
    max_slide_count: int | None = Field(default=None, ge=1)
    intro_duration_seconds: float | None = Field(default=None, ge=0.0)
    assets_dirname: str | None = Field(default=None, min_length=1)
    ber_icons_dirname: str | None = Field(default=None, min_length=1)
    cover_logo_filename: str | None = Field(default=None, min_length=1)
    background_audio_filename: str | None = Field(default=None, min_length=1)
    audio_volume: float | None = Field(default=None, ge=0.0)
    ffmpeg_filter_threads: int | None = Field(default=None, ge=0)
    ffmpeg_encoder_threads: int | None = Field(default=None, ge=0)
    font_path: str | None = Field(default=None, min_length=1)
    bold_font_path: str | None = Field(default=None, min_length=1)
    subtitle_font_path: str | None = Field(default=None, min_length=1)
    subtitle_font_size: int | None = Field(default=None, ge=1)
    ber_icon_scale: float | None = Field(default=None, gt=0.0)
    agency_logo_scale: float | None = Field(default=None, gt=0.0)
    include_intro: bool | None = None
    footer_bottom_offset_px: int | None = Field(default=None, ge=0)

    def to_template_overrides(self) -> dict[str, object]:
        overrides = self.model_dump(exclude_none=True)
        for field_name in ("font_path", "bold_font_path", "subtitle_font_path"):
            raw_value = overrides.get(field_name)
            if raw_value is not None:
                overrides[field_name] = Path(str(raw_value)).expanduser()
        return overrides


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

        site_id = _require_text(payload, "site_id")
        source_property_id = _require_int(payload, "source_property_id")

        with self.unit_of_work_factory() as unit_of_work:
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
            _replace_atomically(request_manifest_path, final_request_manifest_path)
            _replace_atomically(resolved_manifest_path, final_manifest_path)
            _replace_atomically(media_path, final_video_path)
            self._save_artifact(
                ScriptedVideoArtifactRecord(
                    render_id=render_id,
                    site_id=site_id,
                    source_property_id=source_property_id,
                    property_slug=property_record.slug,
                    render_profile=render_profile,
                    status="rendered",
                    request_manifest_json=resolved_request.request_manifest_json,
                    request_manifest_path=_relative_path_text(self.workspace_dir, final_request_manifest_path),
                    resolved_manifest_path=_relative_path_text(self.workspace_dir, final_manifest_path),
                    media_path=_relative_path_text(self.workspace_dir, final_video_path),
                    error_message="",
                    created_at="",
                    updated_at="",
                )
            )
            return ScriptedVideoRenderResult(
                render_id=render_id,
                site_id=site_id,
                source_property_id=source_property_id,
                video_path=_relative_path_text(self.workspace_dir, final_video_path),
                manifest_path=_relative_path_text(self.workspace_dir, final_manifest_path),
                request_manifest_path=_relative_path_text(self.workspace_dir, final_request_manifest_path),
            )
        except ApplicationError as error:
            shutil.rmtree(final_dir, ignore_errors=True)
            self._save_artifact(
                ScriptedVideoArtifactRecord(
                    render_id=render_id,
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
        title = _require_text(payload, "title")
        property_status = _require_text(payload, "property_status")
        slides = _resolve_slides(payload, workspace_dir=self.workspace_dir)
        request_manifest_json = json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True)

        defaults_property = Property(
            id=source_property_id,
            slug=property_slug,
            property_status=property_status,
            price=_optional_text(payload, "price"),
            price_term=_optional_text(payload, "price_term"),
        )
        delivery_plan = build_media_delivery_plan(defaults_property)

        render_profile = _optional_text(payload, "render_profile") or delivery_plan.render_profile
        template = build_reel_template_for_render_profile(
            render_profile,
            template=_resolve_scripted_render_template(payload),
        )
        listing_lifecycle = _optional_text(payload, "listing_lifecycle") or delivery_plan.listing_lifecycle
        banner_text = (
            _optional_text_allow_blank(payload, "banner_text")
            if "banner_text" in payload
            else delivery_plan.banner_text
        )
        price_display_text = (
            _optional_text_allow_blank(payload, "price_display_text")
            if "price_display_text" in payload
            else delivery_plan.price_display_text
        )
        background_audio_path = None
        if "background_audio_path" in payload:
            background_audio_path = _resolve_local_file_path(
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
            link=_optional_text(payload, "link"),
            property_status=property_status,
            selected_image_dir=self.workspace_dir,
            selected_image_paths=tuple(slide.image_path for slide in slides),
            featured_image_url=_optional_text(payload, "featured_image_url"),
            bedrooms=_optional_int(payload, "bedrooms"),
            bathrooms=_optional_int(payload, "bathrooms"),
            ber_rating=_optional_text(payload, "ber_rating"),
            agent_name=_optional_text(payload, "agent_name"),
            agent_photo_url=_optional_text(payload, "agent_photo_url"),
            agent_email=_optional_text(payload, "agent_email"),
            agent_mobile=_optional_text(payload, "agent_mobile"),
            agent_number=_optional_text(payload, "agent_number"),
            price=_optional_text(payload, "price"),
            property_type_label=_optional_text(payload, "property_type_label"),
            property_area_label=_optional_text(payload, "property_area_label"),
            property_county_label=_optional_text(payload, "property_county_label"),
            eircode=_optional_text(payload, "eircode"),
            selected_slides=tuple(slides),
            property_size=_optional_text(payload, "property_size"),
            agency_psra=_optional_text(payload, "agency_psra"),
            agency_logo_url=_optional_text(payload, "agency_logo_url"),
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


def _resolve_scripted_render_template(payload: Mapping[str, object]) -> PropertyReelTemplate:
    raw_render_settings = payload.get("render_settings")
    if raw_render_settings is None:
        return PropertyReelTemplate()
    if not isinstance(raw_render_settings, Mapping):
        raise ValidationError(
            "render_settings must be a JSON object.",
            code="INVALID_RENDER_SETTINGS",
            context={"field": "render_settings"},
            hint="Send render_settings as an object whose keys match the supported reel template fields.",
        )
    try:
        requested_settings = _ScriptedRenderSettingsPayload.model_validate(dict(raw_render_settings))
    except PydanticValidationError as exc:
        issues: list[str] = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()))
            message = str(error.get("msg") or "Invalid value")
            issues.append(f"{location}: {message}" if location else message)
        raise ValidationError(
            "render_settings is invalid.",
            code="INVALID_RENDER_SETTINGS",
            context={"field": "render_settings", "issues": issues},
            hint="Use only supported render_settings fields with valid value types and ranges.",
            cause=exc,
        ) from exc

    overrides = requested_settings.to_template_overrides()
    return replace(PropertyReelTemplate(), **overrides) if overrides else PropertyReelTemplate()


def _resolve_slides(
    payload: Mapping[str, object],
    *,
    workspace_dir: Path,
) -> tuple[PropertyReelSlide, ...]:
    raw_slides = payload.get("slides")
    if not isinstance(raw_slides, Sequence) or isinstance(raw_slides, (str, bytes, bytearray)):
        raise ValidationError(
            "The scripted render payload must include a non-empty slides array.",
            code="SLIDES_REQUIRED",
            context={"field": "slides"},
            hint="Send at least one slide with image_path or a single-entry sources array.",
        )
    slides: list[PropertyReelSlide] = []
    for index, raw_slide in enumerate(raw_slides, start=1):
        if not isinstance(raw_slide, Mapping):
            raise ValidationError(
                "Each slide must be a JSON object.",
                code="INVALID_SLIDE",
                context={"slide_index": index},
                hint="Each slide must include image_path or sources plus an optional caption.",
            )
        image_path_present = "image_path" in raw_slide
        sources_present = "sources" in raw_slide
        if image_path_present and sources_present:
            raise ValidationError(
                "Each slide must use either image_path or sources, not both.",
                code="AMBIGUOUS_SLIDE_SOURCE",
                context={"slide_index": index},
                hint="Choose one source style per slide.",
            )
        if image_path_present:
            slide_path = _resolve_local_file_path(
                raw_slide.get("image_path"),
                workspace_dir=workspace_dir,
                code="INVALID_SLIDE_IMAGE_PATH",
                field_name=f"slides[{index - 1}].image_path",
                hint="Use a readable local image path inside the workspace.",
            )
        elif sources_present:
            sources = raw_slide.get("sources")
            if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes, bytearray)) or not sources:
                raise ValidationError(
                    "Slide sources must be a non-empty array.",
                    code="INVALID_SLIDE_SOURCES",
                    context={"slide_index": index},
                    hint="Send exactly one local source path in v1.",
                )
            if len(sources) > 1:
                raise ValidationError(
                    "Slides with more than one source are not supported yet.",
                    code="COMPOSITE_SLIDE_NOT_SUPPORTED",
                    context={"slide_index": index, "source_count": len(sources)},
                    hint="Send exactly one source for now; composite slides will be added later.",
                )
            slide_path = _resolve_local_file_path(
                _extract_source_path(sources[0], slide_index=index),
                workspace_dir=workspace_dir,
                code="INVALID_SLIDE_IMAGE_PATH",
                field_name=f"slides[{index - 1}].sources[0].path",
                hint="Use a readable local image path inside the workspace.",
            )
        else:
            raise ValidationError(
                "Each slide must include image_path or sources.",
                code="SLIDE_SOURCE_REQUIRED",
                context={"slide_index": index},
                hint="Provide one local image path for each slide.",
            )
        slides.append(
            PropertyReelSlide(
                image_path=slide_path,
                caption=_optional_text(raw_slide, "caption"),
            )
        )

    if not slides:
        raise ValidationError(
            "The scripted render payload must include at least one slide.",
            code="SLIDES_REQUIRED",
            context={"field": "slides"},
            hint="Send at least one slide with image_path or a single-entry sources array.",
        )
    return tuple(slides)


def _extract_source_path(raw_source: object, *, slide_index: int) -> object:
    if isinstance(raw_source, Mapping):
        return raw_source.get("path")
    if isinstance(raw_source, str):
        return raw_source
    raise ValidationError(
        "Each slide source must be a string path or an object containing path.",
        code="INVALID_SLIDE_SOURCE",
        context={"slide_index": slide_index},
        hint="Use sources like [{\"path\": \"generated_media/site/file.jpg\"}].",
    )


def _resolve_local_file_path(
    raw_value: object,
    *,
    workspace_dir: Path,
    code: str,
    field_name: str,
    hint: str,
) -> Path:
    raw_text = _coerce_text(raw_value)
    if raw_text is None:
        raise ValidationError(
            f"{field_name} is required.",
            code=code,
            context={"field": field_name},
            hint=hint,
        )
    parsed = urlparse(raw_text)
    is_windows_drive_path = len(raw_text) >= 2 and raw_text[1] == ":" and raw_text[0].isalpha()
    if parsed.scheme and parsed.scheme.lower() not in {"file"} and not is_windows_drive_path:
        raise ValidationError(
            f"{field_name} must be a local file path.",
            code=code,
            context={"field": field_name, "value": raw_text},
            hint=hint,
        )
    candidate_text = parsed.path if parsed.scheme.lower() == "file" else raw_text
    candidate = Path(candidate_text).expanduser()
    resolved_path = candidate.resolve() if candidate.is_absolute() else (workspace_dir / candidate).resolve()
    try:
        resolved_path.relative_to(workspace_dir)
    except ValueError as exc:
        raise ValidationError(
            f"{field_name} must stay within the workspace.",
            code=code,
            context={"field": field_name, "value": raw_text},
            hint=hint,
            cause=exc,
        ) from exc
    if not resolved_path.exists() or not resolved_path.is_file():
        raise ValidationError(
            f"{field_name} must point to an existing local file.",
            code=code,
            context={"field": field_name, "value": raw_text},
            hint=hint,
        )
    return resolved_path


def _replace_atomically(source_path: Path, destination_path: Path) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination_path.with_suffix(f"{destination_path.suffix}.tmp")
    shutil.copy2(source_path, temporary_path)
    os.replace(temporary_path, destination_path)


def _relative_path_text(base_dir: Path, path: Path | None) -> str:
    if path is None:
        return ""
    resolved_path = path.resolve()
    try:
        return str(resolved_path.relative_to(base_dir))
    except ValueError:
        return str(resolved_path)


def _coerce_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    text = str(value).strip()
    return text or None


def _require_text(payload: Mapping[str, object], field_name: str) -> str:
    value = _coerce_text(payload.get(field_name))
    if value is None:
        raise ValidationError(
            f"{field_name} is required.",
            code="INVALID_SCRIPTED_RENDER_PAYLOAD",
            context={"field": field_name},
            hint="Provide all required top-level fields before requesting a scripted render.",
        )
    return value


def _optional_text(payload: Mapping[str, object], field_name: str) -> str | None:
    return _coerce_text(payload.get(field_name))


def _optional_text_allow_blank(payload: Mapping[str, object], field_name: str) -> str:
    if field_name not in payload:
        return ""
    raw_value = payload.get(field_name)
    if raw_value is None:
        return ""
    if isinstance(raw_value, str):
        return raw_value.strip()
    if isinstance(raw_value, bool):
        return "true" if raw_value else "false"
    return str(raw_value).strip()


def _require_int(payload: Mapping[str, object], field_name: str) -> int:
    if field_name not in payload:
        raise ValidationError(
            f"{field_name} is required.",
            code="INVALID_SCRIPTED_RENDER_PAYLOAD",
            context={"field": field_name},
            hint="Provide all required top-level fields before requesting a scripted render.",
        )
    return _coerce_int(
        payload.get(field_name),
        field_name=field_name,
        required=True,
    )


def _optional_int(payload: Mapping[str, object], field_name: str) -> int | None:
    return _coerce_int(
        payload.get(field_name),
        field_name=field_name,
        required=False,
    )


def _coerce_int(
    value: object,
    *,
    field_name: str,
    required: bool,
) -> int | None:
    if value is None or value == "":
        if required:
            raise ValidationError(
                f"{field_name} must be an integer.",
                code="INVALID_SCRIPTED_RENDER_PAYLOAD",
                context={"field": field_name},
                hint="Use integer values for numeric manifest fields.",
            )
        return None
    if isinstance(value, bool):
        if required:
            raise ValidationError(
                f"{field_name} must be an integer.",
                code="INVALID_SCRIPTED_RENDER_PAYLOAD",
                context={"field": field_name, "value": value},
                hint="Use integer values for numeric manifest fields.",
            )
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(float(str(value).strip()))
    except ValueError as exc:
        raise ValidationError(
            f"{field_name} must be an integer.",
            code="INVALID_SCRIPTED_RENDER_PAYLOAD",
            context={"field": field_name, "value": value},
            hint="Use integer values for numeric manifest fields.",
            cause=exc,
        ) from exc


__all__ = [
    "ScriptedVideoRenderResult",
    "ScriptedVideoRenderService",
]
