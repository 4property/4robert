"""Pydantic payloads for the agency social-templates endpoint."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SocialTemplatesReplacePayload(BaseModel):
    """Body for `PUT /v1/admin/agencies/{agency_id}/social-templates`.

    Replaces the whole template block: every existing per-platform row is
    dropped and re-inserted from the supplied `templates` map. Each key is
    a platform identifier (`instagram`, `tiktok`, `facebook`, `linkedin`,
    `youtube`, `gbp`, `pinterest`) and the value is the description template.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "templates": {
                    "instagram": "{{property_title}} · {{price}}\n{{short_description}}\n👉 {{booking_link}}",
                    "tiktok": "Just listed in {{neighborhood}} — {{property_title}}\n{{price}} · {{bedrooms}} bed",
                }
            }
        },
    )

    templates: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Mapping of platform identifier to description template. "
            "Unknown keys are accepted so future platforms do not need a "
            "schema bump. Empty map drops all stored templates. Each value "
            "may reference any of the variables in `ALLOWED_TEMPLATE_VARIABLES` "
            "(see `modules.configuration.domain.social_templates_variables`) "
            "using `{{variable_name}}` syntax. Unknown variables are rejected "
            "with 422 `SOCIAL_TEMPLATE_UNKNOWN_VARIABLE`."
        ),
    )


__all__ = ["SocialTemplatesReplacePayload"]
