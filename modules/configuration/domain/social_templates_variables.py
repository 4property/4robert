"""Catalog of variables allowed inside an agency's social template body.

The agency configures `description_template`, `title_template` and a
`hashtags` list per social platform via
`PUT /v1/admin/agencies/{agency_id}/social-templates`. At publish time the
worker substitutes `{{variable}}` placeholders with values extracted from
the property record. Only the placeholders listed here are honoured; the
admin UI surfaces them in a palette so the user picks from a finite set.

The validator on the PUT payload uses this set to reject unknown variables
upfront with a 422 (so the admin sees a clear error instead of silently
publishing a caption that contains a literal `{{cosa_inventada}}`). Both
`description_template` and `title_template` honour the same catalog —
`title_template` reuses the validator helpers below.

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

# Hashtags accepted by the social templates payload. The regex is anchored
# on a leading `#` followed by 1..50 word characters or hyphens (`[\w-]`).
# Maximum number of hashtags per platform is bounded so the admin cannot
# load a caption with hundreds of tags that would be silently truncated by
# the network. The 30 cap mirrors Instagram's hard limit and is the lowest
# bound across the supported networks.
HASHTAG_PATTERN: re.Pattern[str] = re.compile(r"^#[\w-]{1,50}$")
MAX_HASHTAGS_PER_PLATFORM: int = 30


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


def is_valid_hashtag(value: str) -> bool:
    """Return True when `value` matches the hashtag shape `^#[\\w-]{1,50}$`."""
    if not isinstance(value, str):
        return False
    return HASHTAG_PATTERN.match(value) is not None


def find_invalid_hashtags(hashtags: list[str] | tuple[str, ...]) -> list[str]:
    """Return the entries of `hashtags` that do not match `HASHTAG_PATTERN`.

    Order is preserved so the error payload mirrors the admin input. Items
    that are empty after stripping whitespace are reported as invalid so the
    admin does not save a row whose hashtag list contains a phantom blank
    string.
    """
    invalid: list[str] = []
    for raw in hashtags or ():
        candidate = str(raw or "").strip()
        if not candidate or not is_valid_hashtag(candidate):
            invalid.append(str(raw))
    return invalid


__all__ = [
    "ALLOWED_TEMPLATE_VARIABLES",
    "HASHTAG_PATTERN",
    "MAX_HASHTAGS_PER_PLATFORM",
    "TEMPLATE_VARIABLE_PATTERN",
    "extract_template_variables",
    "find_invalid_hashtags",
    "find_unknown_template_variables",
    "is_valid_hashtag",
]
