"""Unit tests pinning the catalog of variables allowed in social templates.

Two contracts are locked here:

1. `ALLOWED_TEMPLATE_VARIABLES` is the contract the admin UI surfaces and the
   PUT validator enforces. The set must stay exactly aligned with the runtime
   substitution table built in
   `modules.reels.application.content_generator._build_property_template_variables`.
2. The shared regex `TEMPLATE_VARIABLE_PATTERN` must capture the same shape
   the pipeline substitutes (`{{variable}}` with optional inner whitespace).
"""

from __future__ import annotations

from dataclasses import dataclass

from modules.configuration.domain.social_templates_variables import (
    ALLOWED_TEMPLATE_VARIABLES,
    TEMPLATE_VARIABLE_PATTERN,
    extract_template_variables,
    find_unknown_template_variables,
)
from modules.reels.application.content_generator import (
    _build_property_template_variables,
)


def test_allowed_template_variables_contains_exactly_the_expected_sixteen_keys() -> None:
    assert ALLOWED_TEMPLATE_VARIABLES == frozenset(
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


def test_allowed_variables_match_runtime_substitution_table() -> None:
    """Lock the two-way sync between contract and runtime.

    If someone adds a new key in `_build_property_template_variables` they
    must also expose it in `ALLOWED_TEMPLATE_VARIABLES` (otherwise the PUT
    validator rejects it and the admin cannot use it). If someone removes a
    key from the runtime table the contract must shrink in lockstep
    (otherwise the admin saves a template that becomes a literal
    `{{stale_key}}` in the published caption).
    """
    runtime_keys = set(
        _build_property_template_variables(_StubProperty(), property_url="x").keys()
    )
    assert runtime_keys == set(ALLOWED_TEMPLATE_VARIABLES)


def test_extract_template_variables_returns_lowercased_names_in_order() -> None:
    template = "{{property_title}} · {{ Price }}\n{{property_title}} again"
    assert extract_template_variables(template) == [
        "property_title",
        "price",
        "property_title",
    ]


def test_extract_template_variables_ignores_malformed_or_empty_input() -> None:
    assert extract_template_variables("") == []
    assert extract_template_variables("no placeholders here") == []
    assert extract_template_variables("{{") == []
    assert extract_template_variables("}}") == []
    assert extract_template_variables("{{ }}") == []
    assert extract_template_variables("{{ has space }}") == []


def test_find_unknown_template_variables_dedupes_and_preserves_order() -> None:
    template = "{{cosa_inventada}} {{property_title}} {{cosa_inventada}} {{otra}}"
    assert find_unknown_template_variables(template) == ["cosa_inventada", "otra"]


def test_find_unknown_template_variables_returns_empty_when_all_allowed() -> None:
    template = "{{property_title}} listed at {{price}} in {{city}}"
    assert find_unknown_template_variables(template) == []


def test_template_variable_pattern_matches_pipeline_regex() -> None:
    """The pattern must capture `{{variable}}` and tolerate inner whitespace.

    The pipeline relies on this exact regex inside
    `render_template_with_property`; any divergence between the validator
    and the substitution engine produces silent caption drift.
    """
    assert TEMPLATE_VARIABLE_PATTERN.findall("{{property_title}}") == ["property_title"]
    assert TEMPLATE_VARIABLE_PATTERN.findall("{{ price }}") == ["price"]
    assert TEMPLATE_VARIABLE_PATTERN.findall("{{ city }} - {{ price }}") == [
        "city",
        "price",
    ]


@dataclass
class _StubProperty:
    title: str = ""
    price: str = ""
    bedrooms: int | None = None
    bathrooms: int | None = None
    property_size: str = ""
    property_type_label: str = ""
    property_county_label: str = ""
    property_area_label: str = ""
    eircode: str = ""
    excerpt_html: str = ""
    agent_name: str = ""
    agent_mobile: str = ""
    agent_number: str = ""
    agent_email: str = ""
