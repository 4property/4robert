"""Pydantic payloads for the agency reel-defaults endpoint."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ReelDefaultsUpsertPayload(BaseModel):
    """Body for `PUT /v1/admin/agencies/{agency_id}/defaults`.

    Defaults is the canonical owner of `platforms` (which channels reels
    publish to). The free-form `settings` dict mirrors the frontend
    INITIAL_DEFAULTS shape (currency, language, aspect, resolution, fps,
    subFont, subSize, subBgStyle, musicVolume, kenBurns, introCard,
    outroCard, etc.) and is merged shallow with the previously stored
    object.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "platforms": ["instagram", "tiktok", "facebook", "gbp"],
                "duration_seconds": 30,
                "intro_enabled": True,
                "music_id": "default-track",
                "caption_template": "{{property_title}} · {{price}}",
                "settings": {
                    "currency": "EUR",
                    "language": "en-IE",
                    "aspect": "3:4",
                    "resolution": "1080p",
                    "fps": "30",
                    "subFont": "Inter",
                    "subSize": 44,
                    "subBgStyle": "pill",
                    "musicVolume": 65,
                    "kenBurns": True,
                    "introCard": True,
                    "outroCard": True,
                },
            }
        },
    )

    platforms: list[str] | None = Field(
        default=None,
        description="Social platforms the reel should be published to.",
        examples=[["instagram", "tiktok", "facebook", "gbp"]],
    )
    duration_seconds: int | None = Field(
        default=None,
        ge=5,
        le=180,
        description="Target reel duration in seconds when no override is given.",
        examples=[30],
    )
    music_id: str | None = Field(
        default=None,
        description="Identifier of the music track used by default.",
    )
    intro_enabled: bool | None = Field(
        default=None,
        description="Whether to render an intro card at the start of every reel.",
    )
    caption_template: str | None = Field(
        default=None,
        description="Default caption template used by the publisher.",
    )
    settings: dict | None = Field(
        default=None,
        description=(
            "Free-form rendering defaults (frontend INITIAL_DEFAULTS shape). "
            "Stored verbatim under `agency_reel_defaults.settings` (jsonb)."
        ),
    )


__all__ = ["ReelDefaultsUpsertPayload"]
