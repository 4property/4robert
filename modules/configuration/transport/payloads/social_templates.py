"""Pydantic payloads for the agency social-templates endpoint."""

from __future__ import annotations

from typing import Union

from pydantic import BaseModel, ConfigDict, Field


class SocialTemplateRichPayload(BaseModel):
    """Rich shape for a single platform inside the templates map.

    Backward-compat: the admin form historically posted
    ``templates[platform] = "<description>"`` (a plain string). The frontend
    now sends a richer object so the admin can also configure a per-platform
    ``title_template`` (used by networks that accept a separate title, e.g.
    Pinterest/YouTube) and a list of canned ``hashtags`` appended to the
    description at publish time.

    Both ``description_template`` and ``title_template`` honour the same
    `{{variable}}` catalog defined in
    ``modules.configuration.domain.social_templates_variables``. Hashtags
    are stored verbatim and must match ``^#[\\w-]{1,50}$`` (validated by
    the router).
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "description_template": "{{property_title}} · {{price}}",
                "title_template": "{{property_title}} in {{city}}",
                "hashtags": ["#realestate", "#dublin"],
            }
        },
    )

    description_template: str = Field(
        default="",
        description=(
            "The caption body used for the platform. Empty string keeps the "
            "platform's row but drops the description (the deterministic "
            "fallback caption built from the property record is used at "
            "publish time)."
        ),
    )
    title_template: str = Field(
        default="",
        description=(
            "Optional title template substituted at publish time and forwarded "
            "to networks that accept a dedicated title (Pinterest, YouTube). "
            "Empty string means no title is sent. References the same "
            "`{{variable}}` catalog as `description_template`."
        ),
    )
    hashtags: list[str] = Field(
        default_factory=list,
        description=(
            "Up to 30 hashtags appended at publish time to the rendered "
            "description with `\\n\\n` separator. Each entry must match "
            "`^#[\\w-]{1,50}$`."
        ),
    )


SocialTemplateValuePayload = Union[str, SocialTemplateRichPayload]


class SocialTemplatesReplacePayload(BaseModel):
    """Body for `PUT /v1/admin/agencies/{agency_id}/social-templates`.

    Replaces the whole template block: every existing per-platform row is
    dropped and re-inserted from the supplied `templates` map. Each key is
    a platform identifier (`instagram`, `tiktok`, `facebook`, `linkedin`,
    `youtube`, `gbp`, `pinterest`) and the value is either:

    - a plain string — treated as ``description_template`` (legacy shape,
      kept for backward-compat with admin clients pinned to the v1 contract).
    - a :class:`SocialTemplateRichPayload` — the full per-platform record
      (description + title + hashtags).
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "templates": {
                    "instagram": {
                        "description_template": "{{property_title}} · {{price}}\n{{short_description}}\n👉 {{booking_link}}",
                        "title_template": "",
                        "hashtags": ["#realestate", "#dublin"],
                    },
                    "tiktok": "Just listed in {{neighborhood}} — {{property_title}}",
                }
            }
        },
    )

    templates: dict[str, SocialTemplateValuePayload] | None = Field(
        default_factory=dict,
        description=(
            "Mapping of platform identifier to template payload. Values may "
            "be a plain string (legacy: the description template) or a rich "
            "object exposing `description_template`, `title_template`, and "
            "`hashtags`. Unknown keys are accepted so future platforms do "
            "not need a schema bump. Empty map drops all stored templates. "
            "Templates may reference any of the variables in "
            "`ALLOWED_TEMPLATE_VARIABLES` (see "
            "`modules.configuration.domain.social_templates_variables`) "
            "using `{{variable_name}}` syntax. Unknown variables are rejected "
            "with 422 `SOCIAL_TEMPLATE_UNKNOWN_VARIABLE`; invalid hashtags or "
            "more than 30 hashtags per platform are rejected with 422 "
            "`SOCIAL_TEMPLATE_INVALID_HASHTAG`."
        ),
    )


__all__ = [
    "SocialTemplateRichPayload",
    "SocialTemplateValuePayload",
    "SocialTemplatesReplacePayload",
]
