"""Unit tests for HTML entity decoding inside the deterministic content generator.

Feature 12 `unescape_html_entities_everywhere` — the rendering pipeline and the
GHL POST body must never carry raw HTML entities (e.g. ``&#8217;``, ``&amp;``,
``&quot;``, ``&#x2019;``) emitted by WordPress in ``title.rendered`` and
``content.rendered``. The deterministic content generator substitutes those
fields into the agency template, so we decode at the point of substitution.

The six required cases (decimal numeric, hex numeric, named, nested,
idempotency, empty input) are split across the three integration points that
feature 12 mandates: this file covers the content_generator point.
"""

from __future__ import annotations

import sys
from pathlib import Path

APPLICATION_ROOT = Path(__file__).resolve().parents[3]
if str(APPLICATION_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLICATION_ROOT))

from modules.catalog.domain.wordpress_property import Property
from modules.reels.application.content_generator import (
    DeterministicPropertyContentGenerator,
    render_template_with_property,
)


def _build_property(*, title: str) -> Property:
    return Property.from_api_payload(
        {
            "id": 4242,
            "slug": "feature-12-sample",
            "title": {"rendered": title},
            "content": {"rendered": ""},
        }
    )


def test_render_template_decodes_decimal_numeric_entity_in_property_title() -> None:
    property_item = _build_property(title="Dublin&#8217;s Best Home")

    rendered = render_template_with_property(
        "{{property_title}}",
        property_item,
        property_url="https://example.com/p/feature-12-sample",
    )

    assert rendered == "Dublin’s Best Home"


def test_render_template_decodes_hex_numeric_entity_in_property_title() -> None:
    property_item = _build_property(title="Owner&#x2019;s Suite")

    rendered = render_template_with_property(
        "{{property_title}}",
        property_item,
        property_url="https://example.com/p/feature-12-sample",
    )

    assert rendered == "Owner’s Suite"


def test_render_template_decodes_named_entities() -> None:
    property_item = _build_property(title="Smith &amp; Sons &quot;Premium&quot;")

    rendered = render_template_with_property(
        "{{property_title}}",
        property_item,
        property_url="https://example.com/p/feature-12-sample",
    )

    assert rendered == 'Smith & Sons "Premium"'


def test_render_template_decodes_nested_entities_one_level() -> None:
    """html.unescape only decodes one level per call.

    A doubly-encoded entity ``&amp;amp;`` decodes to ``&amp;`` (NOT ``&``). We
    pin this behavior so reviewers know what to expect downstream — the
    WordPress source only double-encodes when an upstream plugin has already
    escaped, and re-running the pipeline must be idempotent (see the
    idempotency test below) without silently collapsing the ampersand twice.
    """
    property_item = _build_property(title="A &amp;amp; B")

    rendered = render_template_with_property(
        "{{property_title}}",
        property_item,
        property_url="https://example.com/p/feature-12-sample",
    )

    assert rendered == "A &amp; B"


def test_render_template_is_idempotent_on_already_decoded_title() -> None:
    property_item = _build_property(title="Dublin’s Best Home")

    first_pass = render_template_with_property(
        "{{property_title}}",
        property_item,
        property_url="https://example.com/p/feature-12-sample",
    )
    second_pass = render_template_with_property(
        "{{property_title}}",
        first_pass_property(first_pass),
        property_url="https://example.com/p/feature-12-sample",
    )

    assert first_pass == "Dublin’s Best Home"
    assert second_pass == "Dublin’s Best Home"


def first_pass_property(rendered_title: str) -> Property:
    """Helper: re-wrap the rendered title into a Property so we can re-render.

    Kept outside the test body so the assert in the idempotency test reads
    sequentially without a nested helper class.
    """
    return Property.from_api_payload(
        {
            "id": 4242,
            "slug": "feature-12-sample",
            "title": {"rendered": rendered_title},
            "content": {"rendered": ""},
        }
    )


def test_render_template_returns_empty_string_for_blank_template() -> None:
    property_item = _build_property(title="Anything")

    rendered = render_template_with_property(
        "",
        property_item,
        property_url="https://example.com/p/feature-12-sample",
    )

    assert rendered == ""


def test_generate_property_content_uses_decoded_title_in_caption_template() -> None:
    """End-to-end: the public entry point of the generator decodes substituted variables."""
    property_item = _build_property(title="Dublin&#8217;s &amp; Cork &quot;Best&quot;")
    generator = DeterministicPropertyContentGenerator()

    content = generator.generate_property_content(
        property_item=property_item,
        property_url="https://example.com/p/feature-12-sample",
        platforms=("instagram",),
        templates_by_platform={"instagram": "{{property_title}} now listed."},
    )

    instagram_caption = content.captions_by_platform.get("instagram")
    assert instagram_caption is not None
    assert "Dublin’s & Cork \"Best\"" in instagram_caption
    assert "&#8217;" not in instagram_caption
    assert "&amp;" not in instagram_caption
    assert "&quot;" not in instagram_caption
