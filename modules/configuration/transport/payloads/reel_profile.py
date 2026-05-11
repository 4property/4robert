"""Pydantic payload for the aggregated reel-profile admin endpoint.

Powers ``PUT /v1/admin/agencies/{agency_id}/reel-profile``. Same surface
as the legacy ``_AdminReelProfileUpsertPayload`` carried in the retired
``WordPressWebhookServer``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ReelProfileUpsertPayload(BaseModel):
    """Raw, low-level reel-profile body. Used by the admin "Reel settings" tab.

    Prefer the per-section endpoints under ``/v1/admin/agencies/{id}/...``
    (``/brand``, ``/defaults``, ``/automation``, ``/social-templates``,
    ``/music``) for any flow that only needs to edit a single concern.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "name": "Default",
                "platforms": ["instagram", "tiktok", "facebook", "gbp"],
                "duration_seconds": 30,
                "music_id": "uplifting-corporate-1",
                "intro_enabled": True,
                "logo_position": "top-right",
                "brand_primary_color": "#0F172A",
                "brand_secondary_color": "#FFFFFF",
                "caption_template": "{{property_title}} · {{price}}",
                "approval_required": False,
                "extra_settings": {
                    "brand": {"font": "Inter", "tagline": "CKP Estate Agents"},
                    "social_templates": {"instagram": "{{property_title}}\n{{price}}"},
                },
            }
        },
    )

    name: str | None = Field(default=None, description="Profile name (default `Default`).")
    platforms: list[str] | None = Field(
        default=None,
        description="Social platforms the reel should be published to.",
    )
    duration_seconds: int | None = Field(default=None, ge=5, le=180)
    music_id: str | None = None
    intro_enabled: bool | None = None
    logo_position: str | None = Field(default=None, examples=["top-right"])
    brand_primary_color: str | None = Field(default=None, examples=["#0F172A"])
    brand_secondary_color: str | None = Field(default=None, examples=["#FFFFFF"])
    caption_template: str | None = None
    approval_required: bool | None = None
    extra_settings: dict | None = Field(
        default=None,
        description=(
            "Free-form bag of extras. When supplied it REPLACES the "
            "free-form `settings` document on `agency_reel_defaults` "
            "wholesale — use the per-section endpoints for safe partial "
            "edits."
        ),
    )


__all__ = ["ReelProfileUpsertPayload"]
