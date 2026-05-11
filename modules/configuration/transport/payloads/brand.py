"""Pydantic payloads for the agency brand-settings endpoint."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class BrandSettingsUpsertPayload(BaseModel):
    """Body for `PUT /v1/admin/agencies/{agency_id}/brand`.

    Every field is optional so the frontend can save one input at a time
    without resending the whole brand block. Omitted fields preserve the
    previously stored value (or fall back to the per-section default if
    none was stored before).
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "primary_color": "#0F172A",
                "secondary_color": "#FFFFFF",
                "logo_position": "top-right",
                "font_family": "Inter",
                "logo_object_key": "agencies/ckp/logo.png",
                "intro_logo_object_key": "agencies/ckp/intro-logo.png",
            }
        },
    )

    primary_color: str | None = Field(
        default=None,
        description="Primary brand colour, used for accents and overlays. Hex string.",
        examples=["#0F172A"],
    )
    secondary_color: str | None = Field(
        default=None,
        description="Secondary brand colour, used for backgrounds and outro cards.",
        examples=["#FFFFFF"],
    )
    logo_position: str | None = Field(
        default=None,
        description="Watermark anchor on the rendered reel.",
        examples=["top-left", "top-right", "bottom-left", "bottom-right"],
    )
    logo_object_key: str | None = Field(
        default=None,
        description="Object storage key for the watermark logo asset.",
    )
    intro_logo_object_key: str | None = Field(
        default=None,
        description="Object storage key for the intro-card logo asset.",
    )
    font_family: str | None = Field(
        default=None,
        description="Heading font used in the reel and the outro card.",
        examples=["Inter"],
    )


__all__ = ["BrandSettingsUpsertPayload"]
