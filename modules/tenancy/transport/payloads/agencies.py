"""Pydantic payloads for admin agency endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AdminAgencyCreatePayload(BaseModel):
    """Body for `POST /v1/admin/agencies`."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "name": "CKP Estate Agents",
                "slug": "ckp",
                "timezone": "Europe/Dublin",
                "status": "active",
            }
        },
    )

    name: str = Field(min_length=1, description="Display name of the agency.")
    slug: str | None = Field(default=None, description="URL-safe identifier; derived from `name` if blank.")
    timezone: str | None = Field(default=None, description="IANA timezone used for scheduling.")
    status: str | None = Field(default=None, description="Lifecycle status such as `active` or `paused`.")


class AdminAgencyUpdatePayload(BaseModel):
    """Body for `PATCH /v1/admin/agencies/{agency_id}`."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "name": "CKP Estate Agents (Dublin)",
                "status": "active",
            }
        },
    )

    name: str | None = Field(default=None, description="New display name for the agency.")
    slug: str | None = Field(default=None, description="New URL-safe identifier.")
    timezone: str | None = Field(default=None, description="Updated IANA timezone.")
    status: str | None = Field(default=None, description="Updated lifecycle status.")


__all__ = ["AdminAgencyCreatePayload", "AdminAgencyUpdatePayload"]
