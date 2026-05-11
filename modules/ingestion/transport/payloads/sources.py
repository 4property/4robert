"""Pydantic payloads for the ingestion sources admin endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class IngestionSourceCreatePayload(BaseModel):
    """Body for `POST /v1/admin/agencies/{agency_id}/sources`."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "site_id": "ckp.ie",
                "name": "CKP Estate Agents",
                "site_url": "https://ckp.ie",
                "status": "active",
            }
        },
    )

    site_id: str = Field(
        min_length=1,
        description=(
            "Lowercased hostname identifying the WordPress site. Must match "
            "the value sent as `rest_domain` in webhook bodies."
        ),
        examples=["ckp.ie"],
    )
    name: str = Field(min_length=1, description="Display name shown in the admin.")
    kind: str = Field(default="wordpress", description="Ingestion source kind.")
    site_url: str | None = Field(default=None, examples=["https://ckp.ie"])
    normalized_host: str | None = Field(
        default=None,
        description="Defaults to `site_id` lowercased.",
    )
    status: str | None = Field(default=None, examples=["active", "paused"])
    webhook_secret: str | None = Field(
        default=None,
        description="Optional per-site secret used to verify webhook signatures.",
    )


class IngestionSourceUpdatePayload(BaseModel):
    """Body for `PUT /v1/admin/agencies/{agency_id}/sources/{ingestion_source_id}`."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "name": "CKP Estate Agents Dublin",
                "site_url": "https://ckp.ie",
                "status": "active",
            }
        },
    )

    name: str | None = Field(default=None, min_length=1)
    site_url: str | None = Field(default=None)
    normalized_host: str | None = Field(default=None)
    status: str | None = Field(default=None, examples=["active", "paused"])
    webhook_secret: str | None = Field(
        default=None,
        description=(
            "Optional shared secret used to verify webhook signatures. Send the "
            "key (even with empty string) to clear it."
        ),
    )


__all__ = [
    "IngestionSourceCreatePayload",
    "IngestionSourceUpdatePayload",
]
