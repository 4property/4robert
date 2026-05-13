"""Catalog of variables allowed inside an agency's social template body.

The agency configures one `description_template` per social platform via
`PUT /v1/admin/agencies/{agency_id}/social-templates`. At publish time the
worker substitutes `{{variable}}` placeholders with values extracted from
the property record. Only the placeholders listed here are honoured; the
admin UI surfaces them in a palette so the user picks from a finite set.

The validator on the PUT payload uses this set to reject unknown variables
upfront with a 422 (so the admin sees a clear error instead of silently
publishing a caption that contains a literal `{{cosa_inventada}}`).

`modules.reels.application.content_generator._build_property_template_variables`
builds the runtime mapping with exactly these keys — keep both in sync.
"""

from __future__ import annotations

import re

ALLOWED_TEMPLATE_VARIABLES: frozenset[str] = frozenset(
    {
        "property_title",
        "price",
        "bedrooms",
        "bathrooms",
        "size_m2",
        "property_type",
        "city",
        "neighborhood",
        "neighborhood_tag",
        "eircode",
        "short_description",
        "agent_name",
        "agent_phone",
        "agent_email",
        "booking_link",
        "property_url",
    }
)

TEMPLATE_VARIABLE_PATTERN: re.Pattern[str] = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def extract_template_variables(template: str) -> list[str]:
    """Return the lowercased variable names referenced inside `template`.

    Mirrors the substitution rule in `render_template_with_property`: the
    pipeline lowercases the captured key before lookup, so we lowercase here
    too. Duplicate references are preserved in order (callers dedupe if they
    need a set).
    """
    if not template:
        return []
    return [match.group(1).strip().lower() for match in TEMPLATE_VARIABLE_PATTERN.finditer(template)]


def find_unknown_template_variables(template: str) -> list[str]:
    """Return the variables referenced by `template` that are NOT in the catalog.

    Order is preserved and duplicates collapsed so the error message is stable.
    """
    seen: set[str] = set()
    unknown: list[str] = []
    for name in extract_template_variables(template):
        if name in ALLOWED_TEMPLATE_VARIABLES or name in seen:
            continue
        seen.add(name)
        unknown.append(name)
    return unknown


__all__ = [
    "ALLOWED_TEMPLATE_VARIABLES",
    "TEMPLATE_VARIABLE_PATTERN",
    "extract_template_variables",
    "find_unknown_template_variables",
]
