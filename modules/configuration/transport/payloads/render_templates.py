"""Pydantic payloads for agency render-template selection."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RenderTemplateSelectPayload(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={"example": {"template_id": "classic"}},
    )

    template_id: str = Field(
        description="Identifier of the active render template pack.",
        examples=["classic"],
    )


__all__ = ["RenderTemplateSelectPayload"]
