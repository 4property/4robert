"""Pydantic payloads for GoHighLevel session endpoints."""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class GoHighLevelSessionPayload(BaseModel):
    """Body for `POST /v1/sessions/gohighlevel/session`."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "location_id": "v8H1XNB3YCQmVHRhqDoM",
                "user_id": "5lichOFpkqT72Jb7adil",
            }
        },
    )

    location_id: str = Field(
        min_length=1,
        description="The GHL sub-account location id the user opened the app from.",
    )
    user_id: str = Field(
        min_length=1,
        description="The GHL user id resolved from the iframe SSO payload or fallback.",
    )


class GoHighLevelLocationPayload(BaseModel):
    """Body for `POST /v1/sessions/gohighlevel/test`."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={"example": {"location_id": "v8H1XNB3YCQmVHRhqDoM"}},
    )

    location_id: str = Field(
        min_length=1,
        description="GHL location id whose stored access token should be probed.",
    )


class GoHighLevelContextPayload(BaseModel):
    """Body for `POST /v1/sessions/gohighlevel/context`."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        json_schema_extra={"example": {"encryptedData": "U2FsdGVkX1+abc123..."}},
    )

    encrypted_data: str = Field(
        min_length=1,
        validation_alias=AliasChoices("encrypted_data", "encryptedData"),
        description="Encrypted user-context blob received from the GHL parent frame.",
    )


__all__ = [
    "GoHighLevelContextPayload",
    "GoHighLevelLocationPayload",
    "GoHighLevelSessionPayload",
]
