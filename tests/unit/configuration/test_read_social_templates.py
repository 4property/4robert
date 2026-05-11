"""Unit tests for ReadSocialTemplatesUseCase."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.configuration.application.use_cases.read_social_templates import (
    ReadSocialTemplatesUseCase,
)
from shared.errors import ResourceNotFoundError
from tests.unit.configuration._uow_stubs import StubSocialTemplates, build_uow


def test_read_social_templates_returns_listed_records() -> None:
    record = SimpleNamespace(
        agency_id="agency-1",
        platform="instagram",
        description_template="hi",
        title_template="",
        hashtags=(),
        created_at="",
        updated_at="",
    )
    uow = build_uow(social_templates=StubSocialTemplates(existing=(record,)))
    result = ReadSocialTemplatesUseCase().execute(uow=uow, agency_id="agency-1")
    assert result == (record,)


def test_read_social_templates_returns_empty_tuple_when_none_stored() -> None:
    uow = build_uow(social_templates=StubSocialTemplates(existing=()))
    assert (
        ReadSocialTemplatesUseCase().execute(uow=uow, agency_id="agency-1") == ()
    )


def test_read_social_templates_raises_when_agency_missing() -> None:
    uow = build_uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        ReadSocialTemplatesUseCase().execute(uow=uow, agency_id="missing")
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"
