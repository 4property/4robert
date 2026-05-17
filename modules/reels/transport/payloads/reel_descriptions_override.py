"""Pydantic payload for the per-reel description override (feature 21).

The admin "Reels" detail view (in :mod:`modules.reels.transport.http.admin_reels_router`)
exposes ``PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/descriptions``
so the editor can override the auto-generated caption for one or more
platforms before the reel is published.

Validation contract
-------------------

* ``extra='forbid'`` — unknown keys are rejected so the frontend cannot
  smuggle additional fields by mistake (the validator catches the typo
  instead of silently dropping the override).
* ``str_strip_whitespace=True`` — keeps stray leading/trailing whitespace
  out of the persisted payload (the editor textarea otherwise leaks
  trailing newlines).
* ``descriptions_by_platform`` is the only field. Keys are platform
  identifiers matching ``agency_reel_defaults.platforms`` (validated by
  the use case at request time, not here, because the allowed set is
  agency-specific). Values are the already-rendered caption text — the
  frontend sends the materialised string the editor showed the user,
  *not* a Jinja-style template with ``{{ variables }}``. Re-templating
  on submit is intentionally out of scope: if we ever need it, we will
  add a separate "re-render" endpoint rather than overloading this
  payload.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ReelDescriptionsOverridePayload(BaseModel):
    """Body for ``PATCH .../reels/{site_id}/{property_id}/descriptions``."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    descriptions_by_platform: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Platform → rendered caption text. The keys must match the "
            "agency's enabled platforms (``agency_reel_defaults.platforms``); "
            "unknown platforms produce a 422 response. The values are the "
            "final text shown by the frontend after template variables were "
            "substituted — this endpoint does not re-render templates."
        ),
    )


__all__ = ["ReelDescriptionsOverridePayload"]
