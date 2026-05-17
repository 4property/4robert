"""Pydantic payload for the per-reel subtitles override (feature 36).

The admin "Reels" detail view (in
:mod:`modules.reels.transport.http.admin_reels_router`) exposes
``PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/subtitles``
so the editor can pin the on-screen caption text and timing for one reel
before approval / publishing.

Validation contract
-------------------

* ``extra='forbid'`` — unknown keys at the body level and inside each
  cue are rejected so the frontend cannot smuggle additional fields by
  mistake.
* ``cues`` is either ``None`` (clears the override) or a list of
  ``ReelSubtitleCue`` entries. An empty list is also treated as
  "clear" by the use case (the repository normalises both ``None`` and
  ``[]`` to SQL ``NULL``).
* Each cue carries:
    - ``index`` (int >= 0) — unique and monotonically increasing
      across the list (no ``[{index:0},{index:0}]`` and no
      ``[{index:1},{index:0}]``).
    - ``text`` (str, 1-200 graphemes) — the literal subtitle text to
      render. No ``{{ variables }}`` are interpolated.
    - ``in_seconds`` (float >= 0) — cue start time, in seconds from
      the beginning of the reel.
    - ``out_seconds`` (float, > ``in_seconds``) — cue end time.
* Consecutive cues must not overlap:
  ``cues[i].out_seconds <= cues[i+1].in_seconds``.

The Pydantic layer enforces shape + per-cue invariants + cross-cue
monotonicity. The deeper "list cohesion" checks (uniqueness via the
model_validator) catch the cases where the per-cue rules allow input
that the array as a whole must still reject.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


_MAX_TEXT_LENGTH = 200


class ReelSubtitleCue(BaseModel):
    """One cue in the override array."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(
        ...,
        ge=0,
        description=(
            "0-indexed cue slot. Must be unique across the array and "
            "monotonically increasing (``cues[i].index < cues[i+1].index``)."
        ),
    )
    text: str = Field(
        ...,
        min_length=1,
        max_length=_MAX_TEXT_LENGTH,
        description=(
            "Literal subtitle text rendered onscreen. 1-200 characters; "
            "no ``{{ variables }}`` are interpolated."
        ),
    )
    in_seconds: float = Field(
        ...,
        ge=0,
        description=(
            "Cue start time, in seconds from the beginning of the reel. "
            "Must be >= 0 and strictly less than ``out_seconds``."
        ),
    )
    out_seconds: float = Field(
        ...,
        gt=0,
        description=(
            "Cue end time, in seconds from the beginning of the reel. "
            "Must be strictly greater than ``in_seconds``."
        ),
    )

    @model_validator(mode="after")
    def _validate_cue_window(self) -> "ReelSubtitleCue":
        if self.out_seconds <= self.in_seconds:
            raise ValueError(
                "Subtitle cue out_seconds must be strictly greater than "
                f"in_seconds (got in={self.in_seconds}, "
                f"out={self.out_seconds})."
            )
        return self


class ReelSubtitlesOverridePayload(BaseModel):
    """Body for ``PATCH .../reels/{site_id}/{property_id}/subtitles``."""

    model_config = ConfigDict(extra="forbid")

    cues: list[ReelSubtitleCue] | None = Field(
        default=None,
        description=(
            "Ordered list of subtitle cues. ``null`` (or an empty list) "
            "clears any previous override and the renderer falls back to "
            "the autoCaptions flow (when ``automation.autoCaptions`` is "
            "enabled) or to no subtitles otherwise. Otherwise the cues "
            "must have unique monotonically increasing ``index`` keys "
            "and non-overlapping timing windows."
        ),
    )

    @model_validator(mode="after")
    def _validate_cues_array(self) -> "ReelSubtitlesOverridePayload":
        if self.cues is None or not self.cues:
            return self
        previous_index: int | None = None
        previous_out: float | None = None
        for cue in self.cues:
            if previous_index is not None and cue.index <= previous_index:
                raise ValueError(
                    "Subtitle cue indices must be unique and "
                    "monotonically increasing "
                    f"(got {previous_index} then {cue.index})."
                )
            if previous_out is not None and cue.in_seconds < previous_out:
                raise ValueError(
                    "Subtitle cue windows must not overlap "
                    f"(previous out={previous_out}, "
                    f"next in={cue.in_seconds})."
                )
            previous_index = cue.index
            previous_out = cue.out_seconds
        return self


__all__ = [
    "ReelSubtitleCue",
    "ReelSubtitlesOverridePayload",
]
