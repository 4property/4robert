"""Pydantic payload for the per-reel music override (feature 25).

The admin "Reels" detail view (in :mod:`modules.reels.transport.http.admin_reels_router`)
exposes ``PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/music``
so the editor can swap the background music for one reel before it is
approved / published.

Validation contract
-------------------

* ``extra='forbid'`` — unknown keys are rejected so the frontend cannot
  smuggle additional fields by mistake.
* ``str_strip_whitespace=True`` — keeps stray leading/trailing whitespace
  out of the persisted payload.
* ``music_id`` is the only field. A ``None`` (or omitted) value clears
  the override and the next render falls back to the agency pool
  resolved by features 23/24. A non-``None`` value must reference an
  ``agency_music_tracks.id`` row belonging to the same agency as the
  reel — the same-agency invariant is enforced by the use case at
  request time (not here, because the agency id only travels through
  the URL).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ReelMusicOverridePayload(BaseModel):
    """Body for ``PATCH .../reels/{site_id}/{property_id}/music``."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    music_id: str | None = Field(
        default=None,
        description=(
            "Identifier of the ``agency_music_tracks`` row to use for "
            "this reel. ``null`` clears any previous override and the "
            "next render falls back to the agency pool. The id must "
            "reference a track owned by the same agency as the reel."
        ),
    )


__all__ = ["ReelMusicOverridePayload"]
