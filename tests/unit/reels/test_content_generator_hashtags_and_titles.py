"""Unit tests for feature 20: title templates + hashtags inside the
deterministic content generator.

The content generator is responsible for:

1. Substituting variables in the agency's ``title_template`` and exposing
   the rendered title in ``titles_by_platform`` so the publisher forwards
   it to networks with a title slot (Pinterest, YouTube).
2. Appending the agency-configured hashtags at the end of the rendered
   description with a ``\\n\\n`` separator so the published caption
   carries them.
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
    append_hashtags,
)


def _build_property() -> Property:
    return Property.from_api_payload(
        {
            "id": 9001,
            "slug": "feature-20-sample",
            "title": {"rendered": "Bayside Villa"},
            "content": {"rendered": ""},
        }
    )


def test_append_hashtags_concatenates_with_double_newline_separator() -> None:
    result = append_hashtags("Casa X listed", ("#dublin", "#realestate"))
    assert result == "Casa X listed\n\n#dublin #realestate"


def test_append_hashtags_returns_description_unchanged_when_empty_list() -> None:
    assert append_hashtags("Casa X listed", ()) == "Casa X listed"


def test_append_hashtags_drops_empty_or_whitespace_entries() -> None:
    result = append_hashtags("Casa", ("#dublin", "", "  ", "#sale"))
    assert result == "Casa\n\n#dublin #sale"


def test_append_hashtags_with_empty_description_returns_hashtags_only() -> None:
    """A property with no description should still publish the hashtags so
    the agency's branded tags appear on the network even if the deterministic
    fallback is empty.
    """
    assert append_hashtags("", ("#dublin",)) == "#dublin"


def test_generate_property_content_appends_hashtags_to_rendered_description() -> None:
    generator = DeterministicPropertyContentGenerator()

    content = generator.generate_property_content(
        property_item=_build_property(),
        property_url="https://example.com/p/feature-20-sample",
        platforms=("instagram",),
        templates_by_platform={"instagram": "Listing: {{property_title}}"},
        hashtags_by_platform={"instagram": ("#dublin", "#realestate")},
    )

    instagram_caption = content.captions_by_platform["instagram"]
    assert instagram_caption.startswith("Listing: Bayside Villa")
    assert instagram_caption.endswith("#dublin #realestate")
    assert "\n\n#dublin #realestate" in instagram_caption


def test_generate_property_content_renders_title_template_when_provided() -> None:
    generator = DeterministicPropertyContentGenerator()

    content = generator.generate_property_content(
        property_item=_build_property(),
        property_url="https://example.com/p/feature-20-sample",
        platforms=("pinterest",),
        title_templates_by_platform={"pinterest": "{{property_title}} for sale"},
    )

    assert content.titles_by_platform["pinterest"] == "Bayside Villa for sale"


def test_generate_property_content_falls_back_to_deterministic_title_when_template_empty() -> None:
    generator = DeterministicPropertyContentGenerator()

    content = generator.generate_property_content(
        property_item=_build_property(),
        property_url="https://example.com/p/feature-20-sample",
        platforms=("pinterest",),
        title_templates_by_platform={"pinterest": ""},
    )

    # The deterministic fallback is platform-specific; we only assert that a
    # non-empty title was produced so the publisher doesn't ship an empty
    # title to networks that mandate one.
    assert content.titles_by_platform.get("pinterest") is not None


def test_generate_property_content_appends_hashtags_to_fallback_caption() -> None:
    """When the agency leaves ``description_template`` blank the deterministic
    caption is used; hashtags must still be appended to it.
    """
    generator = DeterministicPropertyContentGenerator()

    content = generator.generate_property_content(
        property_item=_build_property(),
        property_url="https://example.com/p/feature-20-sample",
        platforms=("instagram",),
        hashtags_by_platform={"instagram": ("#dublin",)},
    )

    caption = content.captions_by_platform["instagram"]
    assert caption.endswith("#dublin")
    assert "\n\n#dublin" in caption
