"""Read the agency configuration assembled into the legacy reel-profile shape.

The frontend's "Reel settings" tab still consumes a single document
joining brand, defaults, automation, social templates and music. Feature
6 split persistence into per-section tables; this use case composes the
typed aggregates back into the legacy ``ReelProfileRecord.to_public_dict``
shape for the admin drawer.

Returns ``None`` when no section row exists for the agency yet; callers
serialize that as JSON ``null`` to preserve the legacy semantics
("``reel_profile: null``" means "the agency has not configured a profile
yet").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
)
from modules.configuration.domain import (
    AutomationRules,
    BrandSettings,
    MusicTrack,
    ReelDefaults,
    SocialTemplate,
)
from shared.db import DatabaseUnitOfWork


_DEFAULT_PLATFORMS = (
    "tiktok",
    "instagram",
    "linkedin",
    "youtube",
    "facebook",
    "gbp",
    "pinterest",
)


# Feature 24: default the music selection rules block when the agency
# has never persisted one. The default mirrors the pre-feature-24 behaviour
# of `_resolve_agency_music_pool` (fallback to library when default pool
# empty). The default is **only** applied on read; the upsert path keeps
# the JSONB document exactly as sent so the DB never accumulates implicit
# state and a future migration can introduce new sub-keys without legacy
# rows blocking it.
_DEFAULT_MUSIC_SELECTION_RULES: dict[str, Any] = {
    "fallback_to_full_library": True,
}


def _merge_music_selection_rules_default(
    settings: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a copy of ``settings`` with the music selection-rule defaults.

    The merge is non-destructive: keys the agency explicitly persisted
    win over the defaults. The merge is also shallow — only the
    ``selection_rules`` block is back-filled when ``music`` is empty or
    missing; any sibling key the frontend adds under ``music.*`` keeps
    its value verbatim. The function never mutates its input.
    """
    merged: dict[str, Any] = dict(settings)
    raw_music = merged.get("music")
    music_dict: dict[str, Any]
    if isinstance(raw_music, Mapping):
        music_dict = dict(raw_music)
    else:
        music_dict = {}
    raw_rules = music_dict.get("selection_rules")
    if isinstance(raw_rules, Mapping):
        rules_dict: dict[str, Any] = {
            **_DEFAULT_MUSIC_SELECTION_RULES,
            **dict(raw_rules),
        }
    else:
        rules_dict = dict(_DEFAULT_MUSIC_SELECTION_RULES)
    music_dict["selection_rules"] = rules_dict
    merged["music"] = music_dict
    return merged


def resolve_music_selection_rules(
    settings: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Resolve the effective ``music.selection_rules`` for a settings dict.

    Helper for downstream code (e.g. the reels pipeline) that needs the
    flag with its documented default applied. Returns a fresh dict so
    callers can safely mutate it.
    """
    if not settings:
        return dict(_DEFAULT_MUSIC_SELECTION_RULES)
    raw_music = settings.get("music")
    if not isinstance(raw_music, Mapping):
        return dict(_DEFAULT_MUSIC_SELECTION_RULES)
    raw_rules = raw_music.get("selection_rules")
    if not isinstance(raw_rules, Mapping):
        return dict(_DEFAULT_MUSIC_SELECTION_RULES)
    return {**_DEFAULT_MUSIC_SELECTION_RULES, **dict(raw_rules)}


@dataclass(frozen=True, slots=True)
class AggregatedReelProfile:
    agency_id: str
    brand: BrandSettings | None
    defaults: ReelDefaults | None
    automation: AutomationRules | None
    social_templates: tuple[SocialTemplate, ...]
    music_tracks: tuple[MusicTrack, ...]

    def to_public_dict(self) -> dict[str, Any]:
        """Render the aggregate with the legacy ``reel_profiles`` shape."""
        defaults = self.defaults
        brand = self.brand
        automation = self.automation
        platforms = list(defaults.platforms) if defaults is not None else list(_DEFAULT_PLATFORMS)
        duration_seconds = (
            int(defaults.duration_seconds) if defaults is not None else 30
        )
        music_id = defaults.music_id if defaults is not None else ""
        render_template_id = (
            getattr(defaults, "render_template_id", "classic")
            if defaults is not None
            else "classic"
        )
        intro_enabled = bool(defaults.intro_enabled) if defaults is not None else True
        caption_template = (
            defaults.caption_template if defaults is not None else ""
        )
        logo_position = brand.logo_position if brand is not None else "top-right"
        brand_primary = brand.primary_color if brand is not None else "#0F172A"
        brand_secondary = brand.secondary_color if brand is not None else "#FFFFFF"
        approval_required = (
            bool(automation.approval_required) if automation is not None else False
        )
        extras: Mapping[str, Any] = (
            dict(defaults.settings) if defaults is not None else {}
        )
        # Feature 24: surface the music selection rules with their
        # documented default when the agency has never set them. The
        # default is **not** persisted — it only fills the read shape.
        extras = _merge_music_selection_rules_default(extras)
        if self.social_templates:
            extras = {
                **extras,
                "social_templates": {
                    template.platform: template.description_template
                    for template in self.social_templates
                },
            }
        if self.music_tracks:
            extras = {
                **extras,
                "music_tracks": [
                    {
                        "music_id": track.music_id,
                        "display_name": track.display_name,
                        "object_key": track.object_key,
                        "duration_seconds": track.duration_seconds,
                        "is_default": track.is_default,
                    }
                    for track in self.music_tracks
                ],
            }
        created_at = (
            (defaults.created_at if defaults else "")
            or (brand.created_at if brand else "")
            or (automation.created_at if automation else "")
        )
        updated_at = (
            (defaults.updated_at if defaults else "")
            or (brand.updated_at if brand else "")
            or (automation.updated_at if automation else "")
        )
        return {
            "profile_id": self.agency_id,
            "agency_id": self.agency_id,
            "name": "Default",
            "platforms": platforms,
            "duration_seconds": duration_seconds,
            "music_id": music_id,
            "render_template_id": render_template_id,
            "intro_enabled": intro_enabled,
            "logo_position": logo_position,
            "brand_primary_color": brand_primary,
            "brand_secondary_color": brand_secondary,
            "caption_template": caption_template,
            "approval_required": approval_required,
            "extra_settings": dict(extras),
            "created_at": created_at,
            "updated_at": updated_at,
        }


class ReadAggregatedReelProfileUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
    ) -> AggregatedReelProfile | None:
        if uow.configuration is None:
            raise RuntimeError("The unit of work is not active.")
        normalized_agency_id = str(agency_id or "").strip()
        ensure_agency_exists(uow, normalized_agency_id)

        brand = uow.configuration.brand.get(normalized_agency_id)
        defaults = uow.configuration.defaults.get(normalized_agency_id)
        automation = uow.configuration.automation.get(normalized_agency_id)
        social_templates = uow.configuration.social_templates.list_for_agency(
            normalized_agency_id
        )
        music_tracks = uow.configuration.music.list_for_agency(normalized_agency_id)

        if (
            brand is None
            and defaults is None
            and automation is None
            and not social_templates
            and not music_tracks
        ):
            return None

        return AggregatedReelProfile(
            agency_id=normalized_agency_id,
            brand=brand,
            defaults=defaults,
            automation=automation,
            social_templates=tuple(social_templates),
            music_tracks=tuple(music_tracks),
        )


__all__ = [
    "AggregatedReelProfile",
    "ReadAggregatedReelProfileUseCase",
    "resolve_music_selection_rules",
]
