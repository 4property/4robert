"""Per-agency configuration value objects.

The legacy `reel_profiles` god-table (one row per agency, all configuration
mashed in via `extra_settings_json`) is dissolved into per-section typed
tables: `agency_brand_settings`, `agency_reel_defaults`,
`agency_automation_rules`, `agency_social_templates`, `agency_music_tracks`.

Each section is its own aggregate so the corresponding admin form can save
without touching the others.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class BrandSettings:
    agency_id: str
    primary_color: str
    secondary_color: str
    logo_position: str
    logo_object_key: str
    intro_logo_object_key: str
    font_family: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ReelDefaults:
    agency_id: str
    platforms: tuple[str, ...]
    duration_seconds: int
    music_id: str
    intro_enabled: bool
    caption_template: str
    render_template_id: str = "classic"
    settings: Mapping[str, Any] = field(default_factory=dict)
    outro_enabled: bool = False
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class IntroOutroAsset:
    """Per-agency intro or outro video asset.

    ``source`` is the discriminator that controls how the renderer treats
    the asset: ``'uploaded'`` concatenates the user-supplied MP4/MOV,
    ``'brand_card'`` is reserved for a future auto-generated card (feature
    pending — the renderer treats it as ``'none'`` today), and ``'none'``
    means the agency has no outro and no concat is performed.
    """

    agency_id: str
    kind: str
    object_key: str
    duration_seconds: int
    source: str
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class AutomationRules:
    agency_id: str
    approval_required: bool
    publish_window_start: str
    publish_window_end: str
    publish_days: tuple[str, ...]
    trigger_on_status: tuple[str, ...]
    hold_window_seconds: int
    quiet_hours_enabled: bool
    skip_weekends: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class SocialTemplate:
    agency_id: str
    platform: str
    description_template: str
    title_template: str
    hashtags: tuple[str, ...]
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class SocialTemplateUpsert:
    """Per-platform record bound for ``SocialTemplatesRepository.replace_all_for_agency``.

    Mirrors the rich shape accepted by the PUT payload: ``description_template``
    keeps the legacy caption body, ``title_template`` is forwarded to
    networks that accept a dedicated title (Pinterest, YouTube), and
    ``hashtags`` are appended to the rendered description at publish time.
    """

    description_template: str = ""
    title_template: str = ""
    hashtags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class MusicTrack:
    music_id: str
    agency_id: str
    display_name: str
    object_key: str
    duration_seconds: int
    is_default: bool
    created_at: str


@dataclass(frozen=True, slots=True)
class RenderTemplatePreviewImage:
    kind: str
    image_url: str
    alt: str


@dataclass(frozen=True, slots=True)
class RenderTemplate:
    template_id: str
    display_name: str
    description: str
    status: str
    sort_order: int
    preview_images: tuple[RenderTemplatePreviewImage, ...]
    layout_variant: str
    reel_settings: Mapping[str, Any] = field(default_factory=dict)
    poster_settings: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    @property
    def is_selectable(self) -> bool:
        return self.status == "active"


__all__ = [
    "AutomationRules",
    "BrandSettings",
    "IntroOutroAsset",
    "MusicTrack",
    "RenderTemplate",
    "RenderTemplatePreviewImage",
    "ReelDefaults",
    "SocialTemplate",
    "SocialTemplateUpsert",
]
