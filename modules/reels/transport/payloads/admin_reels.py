"""Pydantic payloads for the admin reels router.

The admin "Reels" view exposes a flat record per reel that joins the
`properties` row, the latest `reels` row, and the most recent
`media_revisions` snapshot. The payloads below mirror the legacy
serializer shape so the frontend can switch transport without changes.

Feature 37 adds the ``ReelSlidesOverridePayload`` plus the per-kind
discriminated union for the ``PATCH .../slides`` editor. The payload
shape lives here (rather than a dedicated module) per the feature-37
spec; the per-kind models mirror the scenes the auto-generated
manifest pipeline produces so the renderer can consume either source
of truth without translation glue.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from modules.reels.transport.payloads.reel_subtitles_override import (
    ReelSubtitleCue,
)


class AgencyReelItemPayload(BaseModel):
    """Flat shape for one reel in the admin "Reels" view."""

    model_config = ConfigDict(extra="forbid")

    site_id: str
    source_property_id: int
    slug: str
    title: str | None = None
    link: str | None = None
    price: str | None = None
    property_status: str | None = None
    property_type_label: str | None = None
    property_area_label: str | None = None
    property_county_label: str | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    featured_image_url: str | None = None
    agent_name: str | None = None
    workflow_state: str = ""
    publish_status: str = ""
    render_status: str = ""
    last_published_location_id: str = ""
    current_revision_id: str = ""
    pipeline_updated_at: str = ""
    pipeline_created_at: str = ""
    fetched_at: str = ""
    revision_media_path: str = ""
    revision_metadata_path: str = ""
    revision_artifact_kind: str = ""
    revision_created_at: str = ""
    # Feature 41: snapshot of the autoCaptions cues the renderer
    # produced on the most recent render whose ``subtitles_override``
    # was NULL. The editor (feature 36) reads this column under the
    # camelCase alias ``publishSubtitlesSnapshot`` as the starting
    # value of the subtitle override before the user types anything.
    # ``None`` when the renderer has never produced a snapshot.
    publish_subtitles_snapshot: list[ReelSubtitleCue] | None = None


class ListReelsResponse(BaseModel):
    """Body for `GET /v1/admin/agencies/{agency_id}/reels` (feature 32).

    The legacy ``count`` field is preserved as an alias of ``len(items)``
    so existing consumers don't break. The pagination metadata lives in
    the new fields ``count_total`` (rows matching the filters across the
    whole agency), ``page``, ``page_size`` and ``has_more``.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[AgencyReelItemPayload]
    count: int
    count_total: int = 0
    page: int = 1
    page_size: int = 25
    has_more: bool = False


class InspectReelResponseItem(AgencyReelItemPayload):
    """Detail item adds a flag and resolved video URL."""

    model_config = ConfigDict(extra="forbid")

    has_video: bool = False
    video_url: str | None = None


class InspectReelResponse(BaseModel):
    """Body for `GET /v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}`."""

    model_config = ConfigDict(extra="forbid")

    reel: InspectReelResponseItem


class RegenerateReelResponse(BaseModel):
    """Body for `POST .../approve` (use case `regenerate_reel`).

    Mirrors the legacy contract: 200 with `publish_enqueued=True/False`
    so the frontend can render the success-without-publish state when
    prerequisites are missing (no raw payload, no GHL connection).
    """

    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="approved")
    publish_enqueued: bool
    event_id: str | None = None
    job_id: str | None = None
    reason: str | None = None
    hint: str | None = None
    reel: AgencyReelItemPayload


class RejectReelResponse(BaseModel):
    """Body for `POST .../reject`."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="rejected")
    reel: AgencyReelItemPayload


class ReelManualRegeneratePayload(BaseModel):
    """Body for ``POST .../reels/{site_id}/{property_id}/regenerate`` (feature 40).

    The manual regenerate endpoint only re-enqueues a render job — it
    does not mutate ``workflow_state`` or ``publish_status``. The body
    is optional: callers may send ``{}`` or omit it entirely. When
    ``reason`` is supplied it is persisted on
    ``jobs.publish_context_json`` (`manual_reason`) for audit log
    triage; it does not change rendering behavior.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "Optional audit string explaining why the editor triggered "
            "the manual re-render. Persisted on the new job's "
            "``publish_context_json.manual_reason`` for traceability "
            "only; the renderer does not consume it."
        ),
    )


# ---------------------------------------------------------------------------
# Feature 37: per-reel slide manifest override
# ---------------------------------------------------------------------------


_ALLOWED_SLIDE_KINDS = frozenset(
    {"photo", "voiceover", "text", "intro_card", "outro_card"}
)


class _SlideBase(BaseModel):
    """Shared shape every slide kind inherits.

    The PATCH layer enforces ``extra='forbid'`` on every member so the
    frontend cannot smuggle unknown fields, and re-validates the
    per-kind required fields. The cross-slide invariants (unique
    ``slide_id``, ``position`` covering ``[0, N)`` exactly once, sum of
    durations ≤ ``target_duration_seconds * 1.5``) live in
    :class:`ReelSlidesOverridePayload._validate_slides_array`.
    """

    model_config = ConfigDict(extra="forbid")

    slide_id: str = Field(
        ...,
        min_length=1,
        description=(
            "Stable identifier for the slide (assigned by the front-end "
            "editor). Must be a non-empty string, unique across the "
            "entire ``slides`` array."
        ),
    )
    position: int = Field(
        ...,
        ge=0,
        description=(
            "0-indexed slot in the final reel. Together with every "
            "other slide's ``position`` must cover the range ``[0, N)`` "
            "exactly once."
        ),
    )
    duration_seconds: float = Field(
        ...,
        gt=0,
        description=(
            "Positive duration in seconds. The sum across every slide "
            "must not exceed ``target_duration_seconds * 1.5`` where "
            "``target_duration_seconds`` is the agency's reel default "
            "(or the system default ``REEL_TOTAL_DURATION_SECONDS`` "
            "when the agency has no row)."
        ),
    )


class PhotoSlide(_SlideBase):
    """Image slide (the current default slide kind for the renderer).

    ``photo_position`` is the index into the property's source photo
    set (matches the feature-35 ``photos_override.position`` semantics)
    — the renderer uses it to pick the underlying image.
    """

    kind: Literal["photo"] = Field(
        ...,
        description=(
            "Discriminator literal — ``photo``. Identifies the slide as "
            "a property image slide."
        ),
    )
    photo_position: int = Field(
        ...,
        ge=0,
        description=(
            "0-indexed slot in the property's photo set. The renderer "
            "uses this to pick the underlying image when assembling the "
            "scene list. Multiple slides may reference the same "
            "``photo_position`` (the cross-slide rule is on ``position`` "
            "and ``slide_id``, not on ``photo_position``)."
        ),
    )


class VoiceoverSlide(_SlideBase):
    """Voiceover-only slide (no visual change, audio overlay).

    Today's renderer does not consume voiceover assets — the entry is
    persisted so the FE can render the editor preview, and so a future
    pass can wire it up without a schema migration.
    """

    kind: Literal["voiceover"] = Field(
        ...,
        description=(
            "Discriminator literal — ``voiceover``. The slide overlays "
            "audio on top of the surrounding visual frames."
        ),
    )
    audio_url: str = Field(
        ...,
        min_length=1,
        description=(
            "URL or workspace-relative path of the audio asset. The "
            "renderer accepts any string today; future tightening (MIME "
            "/ length / signed URL) lives at the use-case layer."
        ),
    )


class TextSlide(_SlideBase):
    """Pure text card (no image)."""

    kind: Literal["text"] = Field(
        ...,
        description=(
            "Discriminator literal — ``text``. The slide displays "
            "a text card with no underlying image."
        ),
    )
    text: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description=(
            "Literal text the renderer burns on the slide. 1-500 "
            "characters, no ``{{ variables }}`` interpolation."
        ),
    )


class IntroCardSlide(_SlideBase):
    """Auto-generated intro card slide.

    ``title`` and ``subtitle`` are optional so the front-end can produce
    a card with branding only (logo, address, etc.) or with copy.
    """

    kind: Literal["intro_card"] = Field(
        ...,
        description=(
            "Discriminator literal — ``intro_card``. Auto-generated "
            "intro card with optional title / subtitle copy."
        ),
    )
    title: str | None = Field(
        default=None,
        description="Optional headline for the intro card.",
    )
    subtitle: str | None = Field(
        default=None,
        description="Optional sub-headline for the intro card.",
    )


class OutroCardSlide(_SlideBase):
    """Auto-generated outro card slide, mirror of ``IntroCardSlide``."""

    kind: Literal["outro_card"] = Field(
        ...,
        description=(
            "Discriminator literal — ``outro_card``. Auto-generated "
            "outro card with optional title / subtitle / CTA copy."
        ),
    )
    title: str | None = Field(
        default=None,
        description="Optional headline for the outro card.",
    )
    subtitle: str | None = Field(
        default=None,
        description="Optional sub-headline for the outro card.",
    )
    call_to_action: str | None = Field(
        default=None,
        description=(
            "Optional CTA text rendered as a clickable affordance "
            "(e.g. ``Book a viewing``)."
        ),
    )


# Pydantic v2 discriminated union. ``Field(discriminator='kind')`` makes
# Pydantic route validation to the matching sub-model based on the
# ``kind`` literal — an unknown ``kind`` value surfaces a clear ``422``
# pointing at the discriminator field, rather than a misleading "extra
# field" error from one of the other branches.
SlideUnion = Annotated[
    Union[
        PhotoSlide,
        VoiceoverSlide,
        TextSlide,
        IntroCardSlide,
        OutroCardSlide,
    ],
    Field(discriminator="kind"),
]


class ReelSlidesOverridePayload(BaseModel):
    """Body for ``PATCH .../reels/{site_id}/{property_id}/slides``.

    The payload is intentionally narrow: the front-end submits the full
    array (no partial edits — the override is replaced wholesale). A
    ``null`` or empty array clears the override and the next render
    falls back to the auto-generated manifest pipeline.

    Validation contract (Pydantic layer):

    * ``extra='forbid'`` at the body level AND on every slide.
    * The ``kind`` discriminator must be one of the five allowed
      values (``photo``, ``voiceover``, ``text``, ``intro_card``,
      ``outro_card``).
    * Each slide enforces ``slide_id``, ``position``, ``duration_seconds``
      shape rules at the base level, and the per-kind extra fields.
    * Cross-slide invariants (unique ``slide_id``, positions covering
      ``[0, N)`` exactly once, sum-of-durations cap) are re-checked at
      the use-case layer so the contract is self-contained.
    """

    model_config = ConfigDict(extra="forbid")

    slides: list[SlideUnion] | None = Field(
        default=None,
        description=(
            "Ordered list of slide entries. ``null`` (or an empty list) "
            "clears any previous override and the renderer falls back to "
            "the auto-generated manifest pipeline. Otherwise the slides "
            "must satisfy the cross-array invariants enforced by the "
            "use case (unique ``slide_id``, positions covering "
            "``[0, N)`` exactly once, sum of ``duration_seconds`` ≤ "
            "``target_duration_seconds * 1.5``)."
        ),
    )

    @model_validator(mode="after")
    def _validate_slides_array(self) -> "ReelSlidesOverridePayload":
        """Reject the cross-slide shape errors Pydantic alone cannot see.

        The use case re-checks every invariant so unit tests against
        the use case stay self-contained; this validator catches the
        same problems at the transport boundary so the FE receives a
        deterministic 422 from FastAPI without entering the use case.
        """
        if self.slides is None or not self.slides:
            return self
        seen_ids: set[str] = set()
        seen_positions: set[int] = set()
        for slide in self.slides:
            normalized_id = (slide.slide_id or "").strip()
            if not normalized_id:
                raise ValueError(
                    "Slide ``slide_id`` must be a non-empty string."
                )
            if normalized_id in seen_ids:
                raise ValueError(
                    "Duplicate ``slide_id`` in the slides override array: "
                    f"{normalized_id!r}."
                )
            seen_ids.add(normalized_id)
            if slide.position in seen_positions:
                raise ValueError(
                    "Duplicate ``position`` in the slides override array: "
                    f"{slide.position}."
                )
            seen_positions.add(slide.position)
        # Coverage check happens here too: positions are unique and
        # non-negative, so we only need to verify the contiguous range.
        if sorted(seen_positions) != list(range(len(self.slides))):
            raise ValueError(
                "Slide ``position`` values must cover the range "
                f"``[0, {len(self.slides)})`` exactly once."
            )
        return self


__all__ = [
    "AgencyReelItemPayload",
    "InspectReelResponse",
    "InspectReelResponseItem",
    "IntroCardSlide",
    "ListReelsResponse",
    "OutroCardSlide",
    "PhotoSlide",
    "ReelManualRegeneratePayload",
    "RegenerateReelResponse",
    "RejectReelResponse",
    "ReelSlidesOverridePayload",
    "SlideUnion",
    "TextSlide",
    "VoiceoverSlide",
]
