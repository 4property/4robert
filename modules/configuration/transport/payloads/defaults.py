"""Pydantic payloads for the agency reel-defaults endpoint."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SettingsMusicSelectionRulesPayload(BaseModel):
    """Selection rules block under ``settings.music.selection_rules``.

    Feature 24: persist the "Fall back to full library if no default
    track exists" Toggle from the frontend MusicRules tab. The toggle
    was decorative pre-feature-24 — Feature 23 hardcoded the equivalent
    behaviour to ``True`` inside
    :func:`modules.reels.application.use_cases._resolve_agency_music_pool`.
    Persisting the flag here lets the render pipeline honour the agency
    preference and lets a future migration introduce additional rules
    without breaking the API shape.

    The default value (``True``) preserves the pre-feature-24 behaviour
    when the agency has never set the toggle. The default is **not**
    persisted on save; it is only applied when the read use case
    surfaces an absent value to the client.
    """

    model_config = ConfigDict(extra="forbid")

    fallback_to_full_library: bool = Field(
        default=True,
        description=(
            "If True, when the agency default music pool is empty the "
            "renderer falls back to the full library. If False, the "
            "renderer raises MUSIC_NO_DEFAULT_TRACKS so the reel fails "
            "loudly instead of silently using a non-default track."
        ),
    )


class SettingsMusicPayload(BaseModel):
    """Typed ``settings.music`` sub-document on ``/defaults``.

    ``selection_rules`` is the only key recognized at this layer today.
    ``extra="forbid"`` rejects unknown keys under ``music.*`` so a typo
    in the frontend payload surfaces as a 422 instead of being silently
    persisted into the free-form JSONB blob.
    """

    model_config = ConfigDict(extra="forbid")

    selection_rules: SettingsMusicSelectionRulesPayload | None = Field(
        default=None,
        description=(
            "Optional selection rules block. When omitted, the renderer "
            "behaves as if `fallback_to_full_library=true`."
        ),
    )


class ReelDefaultsUpsertPayload(BaseModel):
    """Body for `PUT /v1/admin/agencies/{agency_id}/defaults`.

    Defaults is the canonical owner of `platforms` (which channels reels
    publish to). The free-form `settings` dict mirrors the frontend
    INITIAL_DEFAULTS shape (currency, language, aspect, resolution, fps,
    subFont, subSize, subBgStyle, musicVolume, kenBurns, introCard,
    outroCard, etc.) and is merged shallow with the previously stored
    object.

    The `settings.music` sub-document is validated by
    :class:`SettingsMusicPayload` so unknown keys under `music.*` (and
    under `music.selection_rules.*`) are rejected with 422 instead of
    being silently persisted. Other keys under `settings` keep their
    free-form behaviour for forward compatibility with the frontend
    INITIAL_DEFAULTS shape.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "platforms": ["instagram", "tiktok", "facebook", "gbp", "pinterest"],
                "duration_seconds": 30,
                "intro_enabled": True,
                "music_id": "default-track",
                "render_template_id": "classic",
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
                    "music": {
                        "selection_rules": {
                            "fallback_to_full_library": True,
                        },
                    },
                },
            }
        },
    )

    platforms: list[str] | None = Field(
        default=None,
        description="Social platforms the reel should be published to.",
        examples=[["instagram", "tiktok", "facebook", "gbp", "pinterest"]],
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
    outro_enabled: bool | None = Field(
        default=None,
        description=(
            "Whether to append the uploaded outro video at the end of every "
            "rendered reel. Effective only when an outro asset has been "
            "uploaded (`outro_source='uploaded'`)."
        ),
    )
    caption_template: str | None = Field(
        default=None,
        description="Default caption template used by the publisher.",
    )
    render_template_id: str | None = Field(
        default=None,
        description="Render template pack selected for agency reels and posters.",
        examples=["classic"],
    )
    settings: dict | None = Field(
        default=None,
        description=(
            "Free-form rendering defaults (frontend INITIAL_DEFAULTS shape). "
            "Stored verbatim under `agency_reel_defaults.settings` (jsonb). "
            "The `music` sub-key is validated by `SettingsMusicPayload` so "
            "unknown keys under `music.*` are rejected with 422."
        ),
    )

    @field_validator("settings")
    @classmethod
    def _validate_settings_music(cls, value: dict | None) -> dict | None:
        """Partial-validate the ``music`` sub-document inside ``settings``.

        Option A: keep ``settings`` as a free-form ``dict`` so the
        frontend INITIAL_DEFAULTS shape (currency, language, aspect,
        etc.) keeps round-tripping verbatim, and validate only the
        ``music`` sub-key against :class:`SettingsMusicPayload`. The
        validator re-emits the parsed model as a plain ``dict`` (via
        ``model_dump(exclude_none=True)``) so the value persisted in
        the JSONB column matches what the client sent — keys the client
        omitted stay omitted (no default leaks into the database).
        """
        if value is None:
            return value
        if "music" not in value:
            return value
        raw_music: Any = value["music"]
        if raw_music is None:
            return value
        if not isinstance(raw_music, dict):
            # Let SettingsMusicPayload surface a structured 422.
            SettingsMusicPayload.model_validate(raw_music)
            return value  # pragma: no cover - validation raises first
        parsed_music = SettingsMusicPayload.model_validate(raw_music)
        normalized_music = parsed_music.model_dump(exclude_none=True)
        return {**value, "music": normalized_music}


__all__ = [
    "ReelDefaultsUpsertPayload",
    "SettingsMusicPayload",
    "SettingsMusicSelectionRulesPayload",
]
