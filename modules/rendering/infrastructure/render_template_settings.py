"""Validation and resolution helpers for DB-backed render templates."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from modules.configuration.domain import RenderTemplate
from modules.rendering.infrastructure.models import (
    PropertyReelTemplate,
    property_reel_template_to_dict,
)
from shared.errors import ValidationError

logger = logging.getLogger(__name__)

CLASSIC_RENDER_TEMPLATE_ID = "classic"
SIDE_BANNER_RENDER_TEMPLATE_ID = "side_banner"
GALAXY_RENDER_TEMPLATE_ID = "galaxy"
SUPPORTED_LAYOUT_VARIANTS = frozenset({"classic", "side_banner", "galaxy"})

# Renderer-internal keys that ride along inside
# ``render_template_reel_settings`` / ``render_template_poster_settings`` but
# do not map to ``PropertyReelTemplate`` fields. The accent fallbacks are
# resolved from ``BrandSettings.primary_color`` during ingestion and read
# back by ``frame_composition._build_render_data`` directly off the
# ``PropertyContext`` settings dict (feature 16). Feature 29 introduces
# ``side_banner_ribbon_background_color`` for the brand secondary color
# cascade consumed by ``preparation.prepare_reel_render_assets``. The
# 2026-05-15 hotfix adds ``side_banner_panel_color`` so the brand
# ``primary_color`` overrides the per-property accent_background_color
# at render time for the side_banner top / bottom panels.
_RENDERER_INTERNAL_OVERRIDE_KEYS = frozenset(
    {
        "fallback_accent_text_color",
        "fallback_accent_background_color",
        "side_banner_ribbon_background_color",
        "side_banner_panel_color",
        # Feature 31: per-agency subtitle styling persisted under
        # ``agency_reel_defaults.settings`` (camelCase ``sub*`` on the
        # frontend, snake_case in the renderer). Stashed by
        # ``ingest_property_into_reel`` and materialised into
        # ``PropertyRenderData.subtitle_style`` by
        # ``frame_composition._build_render_data``. These keys never map
        # to ``PropertyReelTemplate`` fields and must therefore be
        # excluded from the override validator.
        "subtitle_font_family",
        "subtitle_weight",
        "subtitle_color",
        "subtitle_bg_style",
        "subtitle_bg_color",
        "subtitle_bg_opacity",
        "subtitle_position",
        "subtitle_alignment",
        "subtitle_uppercase",
        "subtitle_max_chars",
        "auto_captions_enabled",
    }
)

_POSITIVE_INT_FIELDS = frozenset(
    {
        "width",
        "height",
        "fps",
        "max_slide_count",
        "subtitle_font_size",
    }
)
_NON_NEGATIVE_INT_FIELDS = frozenset(
    {
        "ffmpeg_filter_threads",
        "ffmpeg_encoder_threads",
        "footer_bottom_offset_px",
    }
)
_POSITIVE_FLOAT_FIELDS = frozenset(
    {
        "total_duration_seconds",
        "seconds_per_slide",
    }
)
_NON_NEGATIVE_FLOAT_FIELDS = frozenset(
    {
        "intro_duration_seconds",
        "audio_volume",
        "ber_icon_scale",
        "agency_logo_scale",
    }
)


@dataclass(frozen=True, slots=True)
class ResolvedRenderTemplateSettings:
    template_id: str
    layout_variant: str
    settings_hash: str
    reel_template: PropertyReelTemplate
    poster_template: PropertyReelTemplate

    @property
    def reel_settings(self) -> dict[str, Any]:
        return property_reel_template_to_dict(self.reel_template)

    @property
    def poster_settings(self) -> dict[str, Any]:
        return property_reel_template_to_dict(self.poster_template)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "template_id": self.template_id,
            "layout_variant": self.layout_variant,
            "settings_hash": self.settings_hash,
            "reel_settings": self.reel_settings,
            "poster_settings": self.poster_settings,
        }


def normalize_property_reel_template_overrides(
    overrides: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not overrides:
        return {}
    base_template = PropertyReelTemplate()
    allowed_fields = set(property_reel_template_to_dict(base_template))
    normalized: dict[str, Any] = {}
    for key, value in dict(overrides).items():
        field_name = str(key or "").strip()
        if not field_name:
            continue
        if field_name in _RENDERER_INTERNAL_OVERRIDE_KEYS:
            continue
        if field_name not in allowed_fields:
            raise ValidationError(
                "The render template setting is not supported.",
                code="RENDER_TEMPLATE_SETTING_UNSUPPORTED",
                context={"setting": field_name},
            )
        normalized[field_name] = _coerce_template_value(
            field_name,
            value,
            getattr(base_template, field_name),
        )
    return normalized


def build_property_reel_template_from_overrides(
    overrides: Mapping[str, Any] | None,
) -> PropertyReelTemplate:
    normalized = normalize_property_reel_template_overrides(overrides)
    if not normalized:
        return PropertyReelTemplate()
    return replace(PropertyReelTemplate(), **normalized)


def resolve_render_template_settings(
    template: RenderTemplate | None,
) -> ResolvedRenderTemplateSettings:
    template_id = (
        str(template.template_id or "").strip()
        if template is not None
        else CLASSIC_RENDER_TEMPLATE_ID
    ) or CLASSIC_RENDER_TEMPLATE_ID
    layout_variant = (
        str(template.layout_variant or "").strip()
        if template is not None
        else "classic"
    ) or "classic"
    if layout_variant not in SUPPORTED_LAYOUT_VARIANTS:
        logger.warning(
            "Unsupported render template layout_variant=%s for template_id=%s; "
            "using classic layout.",
            layout_variant,
            template_id,
        )
        layout_variant = "classic"
    reel_template = build_property_reel_template_from_overrides(
        template.reel_settings if template is not None else {}
    )
    poster_template = build_property_reel_template_from_overrides(
        template.poster_settings if template is not None else {}
    )
    hash_payload = {
        "template_id": template_id,
        "layout_variant": layout_variant,
        "reel_settings": property_reel_template_to_dict(reel_template),
        "poster_settings": property_reel_template_to_dict(poster_template),
    }
    settings_hash = hashlib.sha256(
        json.dumps(hash_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return ResolvedRenderTemplateSettings(
        template_id=template_id,
        layout_variant=layout_variant,
        settings_hash=settings_hash,
        reel_template=reel_template,
        poster_template=poster_template,
    )


def _coerce_template_value(field_name: str, value: Any, default_value: Any) -> Any:
    if isinstance(default_value, bool):
        return _coerce_bool(field_name, value)
    if isinstance(default_value, int):
        return _coerce_int(field_name, value)
    if isinstance(default_value, float):
        return _coerce_float(field_name, value)
    if isinstance(default_value, Path):
        return Path(str(value or "").strip())
    return str(value or "").strip()


def _coerce_bool(field_name: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise ValidationError(
        "The render template setting must be boolean.",
        code="RENDER_TEMPLATE_SETTING_INVALID",
        context={"setting": field_name, "value": str(value)},
    )


def _coerce_int(field_name: str, value: Any) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(
            "The render template setting must be an integer.",
            code="RENDER_TEMPLATE_SETTING_INVALID",
            context={"setting": field_name, "value": str(value)},
        ) from error
    if field_name in _POSITIVE_INT_FIELDS and coerced <= 0:
        raise ValidationError(
            "The render template setting must be positive.",
            code="RENDER_TEMPLATE_SETTING_INVALID",
            context={"setting": field_name, "value": coerced},
        )
    if field_name in _NON_NEGATIVE_INT_FIELDS and coerced < 0:
        raise ValidationError(
            "The render template setting must not be negative.",
            code="RENDER_TEMPLATE_SETTING_INVALID",
            context={"setting": field_name, "value": coerced},
        )
    return coerced


def _coerce_float(field_name: str, value: Any) -> float:
    try:
        coerced = float(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(
            "The render template setting must be numeric.",
            code="RENDER_TEMPLATE_SETTING_INVALID",
            context={"setting": field_name, "value": str(value)},
        ) from error
    if field_name in _POSITIVE_FLOAT_FIELDS and coerced <= 0.0:
        raise ValidationError(
            "The render template setting must be positive.",
            code="RENDER_TEMPLATE_SETTING_INVALID",
            context={"setting": field_name, "value": coerced},
        )
    if field_name in _NON_NEGATIVE_FLOAT_FIELDS and coerced < 0.0:
        raise ValidationError(
            "The render template setting must not be negative.",
            code="RENDER_TEMPLATE_SETTING_INVALID",
            context={"setting": field_name, "value": coerced},
        )
    return coerced


__all__ = [
    "CLASSIC_RENDER_TEMPLATE_ID",
    "GALAXY_RENDER_TEMPLATE_ID",
    "ResolvedRenderTemplateSettings",
    "SIDE_BANNER_RENDER_TEMPLATE_ID",
    "SUPPORTED_LAYOUT_VARIANTS",
    "build_property_reel_template_from_overrides",
    "normalize_property_reel_template_overrides",
    "resolve_render_template_settings",
]
