"""Pydantic payloads for the agency brand-settings endpoint."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from modules.configuration.domain.font_catalog import ALLOWED_FONT_FAMILIES


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
        description=(
            "Heading font used in the reel and the outro card. Must match "
            "one of the canonical family names served by "
            "`GET /v1/admin/fonts`. `null` clears the override (the "
            "renderer falls back to Inter)."
        ),
        examples=["Inter"],
    )

    @field_validator("font_family")
    @classmethod
    def _validate_font_family(cls, value: str | None) -> str | None:
        """Reject font families that are not in the catalogue.

        Feature 28: the catalogue is the source of truth used by both
        the frontend dropdown (``GET /v1/admin/fonts``) and the
        ingestion-time resolver in
        :mod:`modules.reels.application.use_cases.ingest_property_into_reel`.
        Persisting a family that the catalogue cannot resolve would
        silently fall back to Inter at render time — surfacing the bad
        value as a 422 here gives the operator an immediate, clear
        error.

        ``None`` and the empty string both pass through as ``None``: a
        cleared override means "use the default" (Inter). The empty
        string variant is accepted because older frontend builds may
        still send ``""`` for "no selection", and the GET serializer
        returns ``""`` post-Reset; both should round-trip without a
        422. Unknown non-empty values raise ``ValueError``; FastAPI's
        default validation handler emits a 422 whose ``detail``
        includes the field path, the rejected value and the allowed
        families listed below.
        """
        if value is None:
            return None
        # ``str_strip_whitespace=True`` already trimmed the value, so an
        # all-whitespace input arrives as ``""``. Collapse it onto
        # ``None`` so the use case treats it as a clear-the-override
        # signal instead of a 422.
        if value == "":
            return None
        if value in ALLOWED_FONT_FAMILIES:
            return value
        allowed = ", ".join(sorted(ALLOWED_FONT_FAMILIES))
        raise ValueError(
            "UNKNOWN_FONT_FAMILY: "
            f"{value!r} is not in the catalogue. "
            f"Allowed families: {allowed}."
        )


__all__ = ["BrandSettingsUpsertPayload"]
