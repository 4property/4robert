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
    settings: Mapping[str, Any] = field(default_factory=dict)
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
class MusicTrack:
    music_id: str
    agency_id: str
    display_name: str
    object_key: str
    duration_seconds: int
    is_default: bool
    created_at: str


__all__ = [
    "AutomationRules",
    "BrandSettings",
    "MusicTrack",
    "ReelDefaults",
    "SocialTemplate",
]
