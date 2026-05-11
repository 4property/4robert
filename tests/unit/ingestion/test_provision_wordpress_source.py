"""Unit tests for ProvisionWordPressSourceUseCase.

Focuses on the validation surface that's hard to exercise via the
integration path. The end-to-end agency-create + source-upsert flow is
covered by ``tests/integration/ingestion/test_wordpress_sources_global_router.py``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.ingestion.application.use_cases.provision_wordpress_source import (
    ProvisionWordPressSourceInput,
    ProvisionWordPressSourceUseCase,
)
from shared.errors import ValidationError


def test_blank_site_id_raises_validation_error() -> None:
    use_case = ProvisionWordPressSourceUseCase()
    with pytest.raises(ValidationError) as exc_info:
        use_case.execute(
            uow=_uow(),
            data=ProvisionWordPressSourceInput(
                site_id="",
                source_name="Some site",
                agency_id=None,
                agency_name="Some Agency",
            ),
        )
    assert exc_info.value.code == "ADMIN_SITE_ID_REQUIRED"


def test_blank_source_name_raises_validation_error() -> None:
    use_case = ProvisionWordPressSourceUseCase()
    with pytest.raises(ValidationError) as exc_info:
        use_case.execute(
            uow=_uow(),
            data=ProvisionWordPressSourceInput(
                site_id="ckp.ie",
                source_name="",
                agency_id="some-agency",
            ),
        )
    assert exc_info.value.code == "ADMIN_SOURCE_NAME_REQUIRED"


def _uow() -> SimpleNamespace:
    return SimpleNamespace(
        ingestion=SimpleNamespace(sources=_SourcesRepo()),
        tenancy=SimpleNamespace(agencies=_AgenciesRepo()),
    )


class _SourcesRepo:
    def list_all(self) -> tuple:
        return ()


class _AgenciesRepo:
    def get_by_id(self, agency_id: str):
        del agency_id
        return None
