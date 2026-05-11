"""Shared social copy builders (platform descriptions + property captions).

The package keeps ``post_copy`` lightweight (no cross-module deps) so it
can be safely imported from
``modules.publishing.infrastructure.adapters.platforms.shared``. The
heavier ``description`` module (which depends on
``adapters.platforms``) is exposed via lazy attribute access through
``__getattr__`` to avoid a circular import.
"""

from modules.publishing.infrastructure.social_copy.post_copy import (
    CaptionLayout,
    DEFAULT_PROPERTY_CAPTION_LAYOUT,
    PropertyCaptionContext,
    SocialCopyBundle,
    build_property_caption,
    build_property_copy_bundle,
    render_property_caption,
)

_LAZY_DESCRIPTION_NAMES = frozenset(
    {
        "TIKTOK_MAX_DESCRIPTION_LENGTH",
        "build_base_social_description",
        "build_platform_description",
        "build_platform_description_for_property",
        "build_platform_descriptions_for_property",
        "build_platform_descriptions_for_property_with_url",
        "build_platform_title_for_property",
        "build_platform_titles_for_property",
        "build_property_public_url",
        "build_tiktok_description",
        "build_tiktok_description_for_property",
        "build_tiktok_description_for_record",
    }
)


def __getattr__(name: str):
    if name in _LAZY_DESCRIPTION_NAMES:
        from modules.publishing.infrastructure.social_copy import description

        return getattr(description, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CaptionLayout",
    "DEFAULT_PROPERTY_CAPTION_LAYOUT",
    "PropertyCaptionContext",
    "SocialCopyBundle",
    "TIKTOK_MAX_DESCRIPTION_LENGTH",
    "build_base_social_description",
    "build_platform_description",
    "build_platform_description_for_property",
    "build_platform_descriptions_for_property",
    "build_platform_descriptions_for_property_with_url",
    "build_platform_title_for_property",
    "build_platform_titles_for_property",
    "build_property_caption",
    "build_property_copy_bundle",
    "build_property_public_url",
    "build_tiktok_description",
    "build_tiktok_description_for_property",
    "build_tiktok_description_for_record",
    "render_property_caption",
]
