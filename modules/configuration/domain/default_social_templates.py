"""Default social template content seeded for every agency on creation.

When a new agency is registered (and as a one-shot backfill for agencies
that pre-date this feature) we pre-populate `agency_social_templates` with
ready-to-publish defaults per platform so users see captions in GoHighLevel
posts out of the box instead of empty strings.

The title defaults to the property address (`{{property_title}}` in
WordPress carries the address as the listing title). The body matches a
listing-style structure (location pin, price, beds/baths, size, short
description, agent contact, CTA url). Google Business Profile uses a
shorter business-listing format with the variables it surfaces best.

These defaults are SAFE to overwrite: callers should only seed them when
no row exists for the given (agency, platform). All variables used live in
`ALLOWED_TEMPLATE_VARIABLES` so the validator will not reject them.
"""

from __future__ import annotations

from typing import Mapping

from .agency_settings import SocialTemplateUpsert

# Title used across every platform: the WP listing title, which is the
# property address.
DEFAULT_TITLE_TEMPLATE: str = "{{property_title}}"

# Body used for every social network EXCEPT Google Business Profile. Mirrors
# the listing structure agents are used to (emoji-prefixed lines, short
# description, agent contact, CTA url).
DEFAULT_DESCRIPTION_TEMPLATE: str = (
    "\U0001F4CD {{property_title}}\n"
    "\U0001F4B6 {{price}}\n"
    "\U0001F6CF {{bedrooms}} Beds | \U0001F6C1 {{bathrooms}} Baths\n"
    "\U0001F4D0 {{size_m2}} sq.m\n"
    "\n"
    "{{short_description}}\n"
    "\n"
    "{{agent_name}} · {{agent_phone}}\n"
    "{{property_url}}"
)

# Body used for Google Business Profile: shorter, business-listing style.
# Drops emojis (GBP renders them poorly), uses dot separators, agent email
# instead of phone, ends with the property URL as the CTA.
DEFAULT_GBP_DESCRIPTION_TEMPLATE: str = (
    "{{price}} · {{bedrooms}} bed · {{size_m2}} sq.m\n"
    "{{property_title}}\n"
    "\n"
    "{{short_description}}\n"
    "\n"
    "{{agent_name}} · {{agent_email}}\n"
    "{{property_url}}"
)

# Platforms seeded by default. Aligned with the seven plataformas the
# product surfaces today (post-feature-19: pinterest is in defaults too).
DEFAULT_PLATFORMS: tuple[str, ...] = (
    "instagram",
    "tiktok",
    "facebook",
    "linkedin",
    "youtube",
    "pinterest",
    "gbp",
)

# Google Business Profile gets the dedicated business-listing body; the
# rest share the listing template.
_GBP_PLATFORMS: frozenset[str] = frozenset({"gbp", "google_business_profile"})


def build_default_social_templates() -> Mapping[str, SocialTemplateUpsert]:
    """Return the canonical `(platform -> SocialTemplateUpsert)` mapping.

    Caller is responsible for not overwriting agency-customized rows: this
    function only assembles the defaults, it does not look at the DB.
    """
    templates: dict[str, SocialTemplateUpsert] = {}
    for platform in DEFAULT_PLATFORMS:
        if platform in _GBP_PLATFORMS:
            body = DEFAULT_GBP_DESCRIPTION_TEMPLATE
        else:
            body = DEFAULT_DESCRIPTION_TEMPLATE
        templates[platform] = SocialTemplateUpsert(
            description_template=body,
            title_template=DEFAULT_TITLE_TEMPLATE,
            hashtags=(),
        )
    return templates


__all__ = [
    "DEFAULT_DESCRIPTION_TEMPLATE",
    "DEFAULT_GBP_DESCRIPTION_TEMPLATE",
    "DEFAULT_PLATFORMS",
    "DEFAULT_TITLE_TEMPLATE",
    "build_default_social_templates",
]
