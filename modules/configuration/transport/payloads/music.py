"""Pydantic payloads for the agency music-library endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MusicTrackPayload(BaseModel):
    """Body for `POST /v1/admin/agencies/{agency_id}/music`.

    Used to register a brand new music track. The `id` is generated server
    side; the client only supplies the descriptive fields.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "display_name": "Sunset Drive",
                "object_key": "agencies/ckp/music/sunset-drive.mp3",
                "duration_seconds": 28,
                "is_default": False,
            }
        },
    )

    display_name: str = Field(
        min_length=1,
        description="Human-readable label shown in the music picker.",
    )
    object_key: str = Field(
        min_length=1,
        description="Object storage key for the audio asset.",
    )
    duration_seconds: int = Field(
        gt=0,
        le=600,
        description="Duration of the track in seconds. Must be positive.",
    )
    is_default: bool = Field(
        default=False,
        description="When true, this track is highlighted as the default for new reels.",
    )


class MusicTrackPatchPayload(BaseModel):
    """Body for `PUT /v1/admin/agencies/{agency_id}/music/{music_id}`.

    Only ``display_name`` and ``is_default`` are editable post-upload.
    ``object_key`` is owned by the upload endpoint (the binary lives on
    disk and the key is opaque to clients) and ``duration_seconds`` is
    derived from ``ffprobe`` — both would corrupt the on-disk/DB
    invariant if clients could rewrite them. ``extra='forbid'`` makes the
    HTTP layer return 422 when either field is supplied (feature 22).
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    display_name: str | None = Field(default=None, min_length=1)
    is_default: bool | None = Field(default=None)


__all__ = ["MusicTrackPatchPayload", "MusicTrackPayload"]
