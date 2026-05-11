"""Pydantic payloads for the agency-scoped GoHighLevel connection endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ProviderConnectionUpsertPayload(BaseModel):
    """Body for `POST` and `PUT /v1/admin/agencies/{agency_id}/ghl-connection`.

    Backwards-compatible with the legacy admin panel: it ships the shape
    `{location_id, user_id, access_token, refresh_token, expires_at, status}`.
    The router maps that to the new `(external_id, secrets, config)` model
    before calling the use case, so the panel keeps working without changes.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "location_id": "v8H1XNB3YCQmVHRhqDoM",
                "user_id": "5lichOFpkqT72Jb7adil",
                "access_token": "ghl-access-token-...",
                "refresh_token": "ghl-refresh-token-...",
                "expires_at": "2026-12-31T00:00:00Z",
                "status": "active",
            }
        },
    )

    location_id: str = Field(
        min_length=1,
        description="GoHighLevel sub-account location id stored as `external_id`.",
    )
    user_id: str | None = Field(
        default=None,
        description="GHL user id; falls back to `manual` when omitted.",
    )
    access_token: str = Field(
        min_length=1,
        description="OAuth access token. Stored encrypted; never echoed back.",
    )
    refresh_token: str | None = Field(
        default="",
        description="OAuth refresh token. Stored encrypted; optional.",
    )
    expires_at: str | None = Field(
        default="",
        description="ISO-8601 expiry of the access token. Optional.",
    )
    status: str | None = Field(
        default=None,
        description="Connection lifecycle status (`active`, `revoked`, ...).",
        examples=["active"],
    )


__all__ = ["ProviderConnectionUpsertPayload"]
