"""Payload validation and coercion helpers for the scripted video render.

Moved from ``application/scripted_render/service.py`` during sub-feature 18b
to keep the main ``render_service.py`` under the ~500 LoC limit.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError as PydanticValidationError

from modules.rendering.infrastructure.models import (
    PropertyReelSlide,
    PropertyReelTemplate,
)
from shared.errors import ValidationError


# Inlined from the retired ``repositories.stores.scripted_video_artifact_store``
# so the legacy worker-flow integration test stays green until feature 18c
# clears the last legacy paths.
@dataclass(slots=True)
class ScriptedVideoArtifactRecord:
    render_id: str
    agency_id: str
    wordpress_source_id: str
    site_id: str
    source_property_id: int
    property_slug: str
    render_profile: str
    status: str
    request_manifest_json: str
    request_manifest_path: str
    resolved_manifest_path: str
    media_path: str
    error_message: str
    created_at: str
    updated_at: str


# Loose alias kept for backwards compat with type hints in this module. The
# concrete object passed at runtime exposes the attributes the body reads.
UnitOfWork = object


@dataclass(frozen=True, slots=True)
class ScriptedVideoRenderResult:
    render_id: str
    site_id: str
    source_property_id: int
    video_path: str
    manifest_path: str
    request_manifest_path: str


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


def resolve_scripted_render_template(payload: Mapping[str, object]) -> PropertyReelTemplate:
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


def resolve_slides(
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
            slide_path = resolve_local_file_path(
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
            slide_path = resolve_local_file_path(
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
                caption=optional_text(raw_slide, "caption"),
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


def resolve_local_file_path(
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


def replace_atomically(source_path: Path, destination_path: Path) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination_path.with_suffix(f"{destination_path.suffix}.tmp")
    shutil.copy2(source_path, temporary_path)
    os.replace(temporary_path, destination_path)


def relative_path_text(base_dir: Path, path: Path | None) -> str:
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


def require_text(payload: Mapping[str, object], field_name: str) -> str:
    value = _coerce_text(payload.get(field_name))
    if value is None:
        raise ValidationError(
            f"{field_name} is required.",
            code="INVALID_SCRIPTED_RENDER_PAYLOAD",
            context={"field": field_name},
            hint="Provide all required top-level fields before requesting a scripted render.",
        )
    return value


def optional_text(payload: Mapping[str, object], field_name: str) -> str | None:
    return _coerce_text(payload.get(field_name))


def optional_text_allow_blank(payload: Mapping[str, object], field_name: str) -> str:
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


def require_int(payload: Mapping[str, object], field_name: str) -> int:
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


def optional_int(payload: Mapping[str, object], field_name: str) -> int | None:
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
    "ScriptedVideoArtifactRecord",
    "ScriptedVideoRenderResult",
    "UnitOfWork",
    "optional_int",
    "optional_text",
    "optional_text_allow_blank",
    "relative_path_text",
    "replace_atomically",
    "require_int",
    "require_text",
    "resolve_local_file_path",
    "resolve_scripted_render_template",
    "resolve_slides",
]
