"""Pydantic payload for the per-reel photos override (feature 35).

The admin "Reels" detail view (in
:mod:`modules.reels.transport.http.admin_reels_router`) exposes
``PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/photos``
so the editor can reorder the property photos and toggle which ones
appear in the rendered reel before approval / publishing.

Validation contract
-------------------

* ``extra='forbid'`` — unknown keys at the body level and inside each
  entry are rejected so the frontend cannot smuggle additional fields
  by mistake.
* ``photos`` is either ``None`` (clears the override) or a list of
  ``ReelPhotosOverrideEntry`` items. An empty list is also treated as
  "clear" by the use case (the repository normalises both ``None`` and
  ``[]`` to SQL ``NULL``).
* Each entry carries a non-negative ``position`` (the 0-indexed slot
  the photo originally occupied) and a strict boolean ``selected``.
* Positions must be unique and cover the range ``[0, N)`` exactly once.
  ``N`` (the number of photos available for the property) is computed
  by the use case at request time; this Pydantic layer only enforces
  the shape (uniqueness + non-negative + type) so the deeper checks
  surface their own ``422`` codes from the use case.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class ReelPhotosOverrideEntry(BaseModel):
    """One entry in the override array: a (position, selected) pair."""

    model_config = ConfigDict(extra="forbid")

    position: int = Field(
        ...,
        ge=0,
        description=(
            "The original 0-indexed photo position the slot points at. "
            "Must be unique across the array and together with every "
            "other entry's ``position`` cover the range ``[0, N)`` "
            "exactly once."
        ),
    )
    selected: StrictBool = Field(
        ...,
        description=(
            "When ``true`` the photo is rendered into the reel; when "
            "``false`` the slot is dropped from the final video."
        ),
    )


class ReelPhotosOverridePayload(BaseModel):
    """Body for ``PATCH .../reels/{site_id}/{property_id}/photos``."""

    model_config = ConfigDict(extra="forbid")

    photos: list[ReelPhotosOverrideEntry] | None = Field(
        default=None,
        description=(
            "Ordered list of slot entries. ``null`` (or an empty list) "
            "clears any previous override and the renderer falls back to "
            "the default order from ``property_images``. Otherwise, "
            "positions must cover ``[0, N)`` exactly once where ``N`` is "
            "the number of source photos for the property."
        ),
    )

    @model_validator(mode="after")
    def _validate_positions_unique(self) -> "ReelPhotosOverridePayload":
        if self.photos is None or not self.photos:
            return self
        seen: set[int] = set()
        for entry in self.photos:
            if entry.position in seen:
                raise ValueError(
                    "Duplicate photo position in the override array: "
                    f"{entry.position}."
                )
            seen.add(entry.position)
        return self


__all__ = [
    "ReelPhotosOverrideEntry",
    "ReelPhotosOverridePayload",
]
