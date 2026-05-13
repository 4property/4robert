"""Unit tests for DB-backed render template settings resolution."""

from __future__ import annotations

import pytest

from modules.configuration.domain import RenderTemplate
from modules.rendering.infrastructure.render_template_settings import (
    SUPPORTED_LAYOUT_VARIANTS,
    normalize_property_reel_template_overrides,
    resolve_render_template_settings,
)
from shared.errors import ValidationError


def test_normalize_property_reel_template_overrides_coerces_supported_values() -> None:
    overrides = normalize_property_reel_template_overrides(
        {
            "width": "720",
            "height": 1280,
            "include_intro": "true",
            "audio_volume": "0.75",
        }
    )

    assert overrides == {
        "width": 720,
        "height": 1280,
        "include_intro": True,
        "audio_volume": 0.75,
    }


def test_normalize_property_reel_template_overrides_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError) as exc_info:
        normalize_property_reel_template_overrides({"unsupported": 1})

    assert exc_info.value.code == "RENDER_TEMPLATE_SETTING_UNSUPPORTED"


def test_resolve_render_template_settings_hash_is_stable_for_same_settings() -> None:
    first = resolve_render_template_settings(
        _template(
            reel_settings={"width": 720, "height": 1280},
            poster_settings={"height": 1200, "width": 900},
        )
    )
    second = resolve_render_template_settings(
        _template(
            reel_settings={"height": 1280, "width": 720},
            poster_settings={"width": 900, "height": 1200},
        )
    )

    assert first.settings_hash == second.settings_hash
    assert first.reel_template.width == 720
    assert first.poster_template.height == 1200


def test_resolve_render_template_settings_hash_changes_when_settings_change() -> None:
    first = resolve_render_template_settings(_template(reel_settings={"width": 720}))
    second = resolve_render_template_settings(_template(reel_settings={"width": 1080}))

    assert first.settings_hash != second.settings_hash


def test_resolve_render_template_settings_falls_back_to_classic_when_missing() -> None:
    resolved = resolve_render_template_settings(None)

    assert resolved.template_id == "classic"
    assert resolved.layout_variant == "classic"
    assert resolved.reel_template.width > 0
    assert resolved.poster_template.width > 0
    assert resolved.settings_hash


def test_supported_layout_variants_includes_classic_and_side_banner() -> None:
    assert "classic" in SUPPORTED_LAYOUT_VARIANTS
    assert "side_banner" in SUPPORTED_LAYOUT_VARIANTS


def test_resolve_render_template_settings_accepts_side_banner_layout_variant() -> None:
    resolved = resolve_render_template_settings(
        _template(template_id="side_banner", layout_variant="side_banner")
    )

    assert resolved.template_id == "side_banner"
    assert resolved.layout_variant == "side_banner"


def test_resolve_render_template_settings_warns_and_falls_back_for_unknown_variant() -> None:
    resolved = resolve_render_template_settings(
        _template(template_id="weird", layout_variant="not_a_variant")
    )

    assert resolved.layout_variant == "classic"


def _template(
    *,
    template_id: str = "compact",
    layout_variant: str = "classic",
    reel_settings: dict[str, object] | None = None,
    poster_settings: dict[str, object] | None = None,
) -> RenderTemplate:
    return RenderTemplate(
        template_id=template_id,
        display_name=template_id.title(),
        description="",
        status="active",
        sort_order=0,
        preview_images=(),
        layout_variant=layout_variant,
        reel_settings=reel_settings or {},
        poster_settings=poster_settings or {},
    )
