"""Unit tests for ReplaceSocialTemplatesUseCase."""

from __future__ import annotations

import pytest

from modules.configuration.application.use_cases.replace_social_templates import (
    ReplaceSocialTemplatesInput,
    ReplaceSocialTemplatesUseCase,
)
from modules.configuration.domain import SocialTemplateUpsert
from shared.errors import ResourceNotFoundError
from tests.unit.configuration._uow_stubs import StubSocialTemplates, build_uow


def test_replace_normalises_platform_keys_lowercase_and_trimmed() -> None:
    repo = StubSocialTemplates()
    uow = build_uow(social_templates=repo)
    ReplaceSocialTemplatesUseCase().execute(
        uow=uow,
        data=ReplaceSocialTemplatesInput(
            agency_id="agency-1",
            templates={
                "Instagram": SocialTemplateUpsert(description_template="ig"),
                " TikTok ": SocialTemplateUpsert(description_template="tt"),
                "": SocialTemplateUpsert(description_template="ignored"),
            },
        ),
    )
    assert len(repo.replace_calls) == 1
    templates = repo.replace_calls[0]["templates"]
    assert set(templates.keys()) == {"instagram", "tiktok"}
    assert templates["instagram"].description_template == "ig"
    assert templates["tiktok"].description_template == "tt"


def test_replace_accepts_empty_map() -> None:
    repo = StubSocialTemplates()
    uow = build_uow(social_templates=repo)
    ReplaceSocialTemplatesUseCase().execute(
        uow=uow,
        data=ReplaceSocialTemplatesInput(agency_id="agency-1", templates={}),
    )
    assert repo.replace_calls[0]["templates"] == {}


def test_replace_persists_title_and_hashtags_alongside_description() -> None:
    repo = StubSocialTemplates()
    uow = build_uow(social_templates=repo)
    ReplaceSocialTemplatesUseCase().execute(
        uow=uow,
        data=ReplaceSocialTemplatesInput(
            agency_id="agency-1",
            templates={
                "pinterest": SocialTemplateUpsert(
                    description_template="See {{property_title}}",
                    title_template="{{property_title}} in {{city}}",
                    hashtags=("#dublin", "#realestate"),
                )
            },
        ),
    )
    saved = repo.replace_calls[0]["templates"]["pinterest"]
    assert saved.description_template == "See {{property_title}}"
    assert saved.title_template == "{{property_title}} in {{city}}"
    assert saved.hashtags == ("#dublin", "#realestate")


def test_replace_raises_when_agency_missing() -> None:
    uow = build_uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        ReplaceSocialTemplatesUseCase().execute(
            uow=uow,
            data=ReplaceSocialTemplatesInput(
                agency_id="missing",
                templates={"instagram": SocialTemplateUpsert(description_template="x")},
            ),
        )
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"
