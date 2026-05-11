"""Pydantic payloads for the global WordPress sources admin endpoints.

These power ``/v1/admin/wordpress-sources`` and
``/v1/admin/wordpress-sources/{site_id}``. Same surface as the legacy
``WordPressWebhookServer`` had — feature 9 only changed the
implementation underneath.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GlobalWordPressSourceUpsertPayload(BaseModel):
    """Body for ``PUT /v1/admin/wordpress-sources/{site_id}``.

    The ``site_id`` is taken from the URL (the value WordPress posts as
    ``rest_domain`` in the webhook body). Omit ``agency_id`` to have the
    endpoint create a placeholder agency on the fly.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "source_name": "Janet Carroll",
                "agency_id": "0c0a2c63-9d24-4f1f-8c2b-22b6a09e4b3e",
                "site_url": "https://janetcarroll.ie",
                "source_status": "active",
            }
        },
    )

    source_name: str = Field(
        min_length=1,
        description="Human-readable name of the WordPress site.",
        examples=["Janet Carroll"],
    )
    agency_id: str | None = Field(
        default=None,
        description="UUID of the owning agency. Leave blank to auto-create.",
    )
    agency_name: str | None = Field(default=None, description="Used when auto-creating the agency.")
    agency_slug: str | None = Field(default=None, description="Used when auto-creating the agency.")
    agency_timezone: str | None = Field(default=None, examples=["Europe/Dublin"])
    agency_status: str | None = Field(default=None, examples=["active"])
    site_url: str | None = Field(
        default=None,
        description="Canonical site URL (used for display only).",
        examples=["https://janetcarroll.ie"],
    )
    normalized_host: str | None = Field(
        default=None,
        description="Hostname stored verbatim. Defaults to the lowercased ``site_id``.",
    )
    source_status: str | None = Field(default=None, examples=["active", "paused"])
    webhook_secret: str | None = Field(
        default=None,
        description="Optional shared secret to require when WEBHOOK_DISABLE_SECURITY is off.",
    )


__all__ = ["GlobalWordPressSourceUpsertPayload"]
