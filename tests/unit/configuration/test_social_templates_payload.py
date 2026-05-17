"""Unit tests for ``SocialTemplateRichPayload`` and the payload union."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from modules.configuration.transport.payloads.social_templates import (
    SocialTemplateRichPayload,
    SocialTemplatesReplacePayload,
)


def test_rich_payload_defaults_keep_description_title_empty_and_hashtags_empty_list() -> None:
    payload = SocialTemplateRichPayload()
    assert payload.description_template == ""
    assert payload.title_template == ""
    assert payload.hashtags == []


def test_rich_payload_strips_whitespace_on_string_fields() -> None:
    payload = SocialTemplateRichPayload(
        description_template="  desc  ",
        title_template="  title  ",
        hashtags=["#one", "#two"],
    )
    assert payload.description_template == "desc"
    assert payload.title_template == "title"
    assert payload.hashtags == ["#one", "#two"]


def test_rich_payload_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SocialTemplateRichPayload(
            description_template="x",
            title_template="y",
            hashtags=[],
            unexpected="value",
        )


def test_replace_payload_accepts_string_value_for_backward_compat() -> None:
    payload = SocialTemplatesReplacePayload.model_validate(
        {"templates": {"instagram": "legacy caption"}}
    )
    assert payload.templates == {"instagram": "legacy caption"}


def test_replace_payload_accepts_rich_value_object() -> None:
    payload = SocialTemplatesReplacePayload.model_validate(
        {
            "templates": {
                "pinterest": {
                    "description_template": "desc",
                    "title_template": "title",
                    "hashtags": ["#tag"],
                }
            }
        }
    )
    pinterest = payload.templates["pinterest"]
    assert isinstance(pinterest, SocialTemplateRichPayload)
    assert pinterest.description_template == "desc"
    assert pinterest.title_template == "title"
    assert pinterest.hashtags == ["#tag"]


def test_replace_payload_mixed_shape_per_platform_is_allowed() -> None:
    """The admin form may upgrade some platforms to the rich shape while
    other platforms remain on the legacy string shape during the rollout.
    """
    payload = SocialTemplatesReplacePayload.model_validate(
        {
            "templates": {
                "instagram": "legacy string",
                "pinterest": {
                    "description_template": "desc",
                    "title_template": "",
                    "hashtags": [],
                },
            }
        }
    )
    assert payload.templates["instagram"] == "legacy string"
    assert isinstance(payload.templates["pinterest"], SocialTemplateRichPayload)
