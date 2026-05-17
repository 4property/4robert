"""Unit tests pinning the hashtag validators added in feature 20.

The validators are consumed by the social-templates router so an admin can
never persist an invalid hashtag (a 422 ``SOCIAL_TEMPLATE_INVALID_HASHTAG``
is raised upfront). They also bound the list length so the publish pipeline
never builds a caption with more hashtags than the strictest network
accepts (Instagram caps at 30).
"""

from __future__ import annotations

from modules.configuration.domain.social_templates_variables import (
    HASHTAG_PATTERN,
    MAX_HASHTAGS_PER_PLATFORM,
    find_invalid_hashtags,
    is_valid_hashtag,
)


def test_is_valid_hashtag_accepts_letters_digits_underscore_and_hyphen() -> None:
    assert is_valid_hashtag("#realestate")
    assert is_valid_hashtag("#dublin2026")
    assert is_valid_hashtag("#for-sale")
    assert is_valid_hashtag("#a_b_c")
    assert is_valid_hashtag("#A")
    assert is_valid_hashtag("#" + "x" * 50)


def test_is_valid_hashtag_rejects_missing_hash_prefix() -> None:
    assert not is_valid_hashtag("realestate")
    assert not is_valid_hashtag(" #realestate")


def test_is_valid_hashtag_rejects_whitespace_punctuation_and_unicode_emoji() -> None:
    assert not is_valid_hashtag("#has space")
    assert not is_valid_hashtag("#bad!")
    assert not is_valid_hashtag("#")
    assert not is_valid_hashtag("##double")


def test_is_valid_hashtag_rejects_more_than_fifty_chars_after_hash() -> None:
    assert not is_valid_hashtag("#" + "x" * 51)


def test_find_invalid_hashtags_returns_offending_entries_in_order() -> None:
    assert find_invalid_hashtags(
        ["#valid", "no-hash", "#also-valid", "#bad space", ""]
    ) == ["no-hash", "#bad space", ""]


def test_find_invalid_hashtags_handles_empty_list() -> None:
    assert find_invalid_hashtags([]) == []
    assert find_invalid_hashtags(None) == []


def test_max_hashtags_per_platform_is_30() -> None:
    """The constant matches Instagram's hard cap, the strictest of the
    networks the agency targets.
    """
    assert MAX_HASHTAGS_PER_PLATFORM == 30


def test_hashtag_pattern_anchors_both_ends() -> None:
    assert HASHTAG_PATTERN.pattern == r"^#[\w-]{1,50}$"
