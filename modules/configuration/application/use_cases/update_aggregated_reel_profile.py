"""Update the agency configuration via the legacy reel-profile shape.

Powers ``PUT /v1/admin/agencies/{agency_id}/reel-profile``. The legacy
"raw" admin endpoint accepted a single document covering brand, defaults
and automation. Feature 6 split persistence into per-section tables;
this use case orchestrates the per-section writes (``brand.upsert``,
``defaults.upsert``, ``automation.upsert``) inside a single
``DatabaseUnitOfWork`` so the response shape stays byte-compatible with
the legacy endpoint.

The ``name`` payload field is preserved on the response only — the typed
schema does not store a per-agency profile name (the value was always
``"Default"`` in production). ``extra_settings``, when supplied,
replaces the free-form ``settings`` document on
``agency_reel_defaults`` wholesale, mirroring the legacy semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
)
from modules.configuration.application.use_cases.read_aggregated_reel_profile import (
    AggregatedReelProfile,
    ReadAggregatedReelProfileUseCase,
)
from shared.db import DatabaseUnitOfWork


@dataclass(frozen=True, slots=True)
class UpdateAggregatedReelProfileInput:
    agency_id: str
    name: str | None = None
    platforms: list[str] | None = None
    duration_seconds: int | None = None
    music_id: str | None = None
    intro_enabled: bool | None = None
    logo_position: str | None = None
    brand_primary_color: str | None = None
    brand_secondary_color: str | None = None
    caption_template: str | None = None
    approval_required: bool | None = None
    extra_settings: Mapping[str, Any] | None = None


class UpdateAggregatedReelProfileUseCase:
    def __init__(
        self,
        *,
        read_aggregated_reel_profile: ReadAggregatedReelProfileUseCase | None = None,
    ) -> None:
        self._read_aggregated_reel_profile = (
            read_aggregated_reel_profile or ReadAggregatedReelProfileUseCase()
        )

    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        data: UpdateAggregatedReelProfileInput,
    ) -> AggregatedReelProfile:
        if uow.configuration is None:
            raise RuntimeError("The unit of work is not active.")
        agency_id = str(data.agency_id or "").strip()
        ensure_agency_exists(uow, agency_id)

        # Brand slice. Only fields explicitly supplied propagate; the
        # repository preserves the previous value otherwise.
        if any(
            value is not None
            for value in (
                data.logo_position,
                data.brand_primary_color,
                data.brand_secondary_color,
            )
        ):
            uow.configuration.brand.upsert(
                agency_id=agency_id,
                primary_color=data.brand_primary_color,
                secondary_color=data.brand_secondary_color,
                logo_position=data.logo_position,
            )

        # Defaults slice. ``extra_settings`` from the legacy payload
        # replaces the free-form ``settings`` mapping wholesale. We always
        # call upsert when *anything* in the defaults block was supplied so
        # the timestamps update consistently.
        defaults_changes = {
            "platforms": data.platforms,
            "duration_seconds": data.duration_seconds,
            "music_id": data.music_id,
            "intro_enabled": data.intro_enabled,
            "caption_template": data.caption_template,
        }
        if any(value is not None for value in defaults_changes.values()) or (
            data.extra_settings is not None
        ):
            uow.configuration.defaults.upsert(
                agency_id=agency_id,
                platforms=data.platforms,
                duration_seconds=data.duration_seconds,
                music_id=data.music_id,
                intro_enabled=data.intro_enabled,
                caption_template=data.caption_template,
                settings=(
                    dict(data.extra_settings)
                    if data.extra_settings is not None
                    else None
                ),
            )

        # Automation slice. Only ``approval_required`` is exposed by the
        # legacy raw endpoint.
        if data.approval_required is not None:
            uow.configuration.automation.upsert(
                agency_id=agency_id,
                approval_required=data.approval_required,
            )

        result = self._read_aggregated_reel_profile.execute(
            uow=uow,
            agency_id=agency_id,
        )
        if result is None:
            # Should be impossible: at least one section was just upserted.
            raise RuntimeError(
                "Aggregated reel profile could not be reloaded after update."
            )
        return result


__all__ = [
    "UpdateAggregatedReelProfileInput",
    "UpdateAggregatedReelProfileUseCase",
]
