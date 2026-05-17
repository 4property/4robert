"""Unit coverage for `_resolve_expected_secret` in the WordPress webhook router.

Pinned-down decision tree:

1. DB record exists with `secrets_encrypted` non-NULL → decrypt and return it,
   ignore env, no warning.
2. DB record exists with `secrets_encrypted=None`, env has secret → return env,
   emit warning.
3. No DB record, no env → return None, no warning.
4. No DB record, env has secret → return env (legacy site without provisioning),
   emit warning.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import patch

from modules.ingestion.domain import IngestionSource
from modules.ingestion.transport.http.wordpress_webhook_router import (
    _resolve_expected_secret,
)


class _StubSourcesRepo:
    def __init__(self, record: IngestionSource | None) -> None:
        self._record = record
        self.calls: list[tuple[str, str]] = []

    def get_by_kind_external_id(
        self, *, kind: str, external_id: str
    ) -> IngestionSource | None:
        self.calls.append((kind, external_id))
        return self._record


def _uow_with(record: IngestionSource | None) -> SimpleNamespace:
    return SimpleNamespace(ingestion=SimpleNamespace(sources=_StubSourcesRepo(record)))


def _record_with_secret(secrets_encrypted: bytes | None) -> IngestionSource:
    return IngestionSource(
        ingestion_source_id="src-1",
        agency_id="agency-1",
        kind="wordpress",
        external_id="site-a",
        name="Site A",
        status="active",
        has_secret=secrets_encrypted is not None,
        secrets_encrypted=secrets_encrypted,
    )


def test_resolve_returns_db_secret_when_record_has_secrets_encrypted(
    caplog,
) -> None:
    record = _record_with_secret(b"<encrypted-blob>")
    uow = _uow_with(record)
    caplog.set_level(logging.WARNING)

    with patch(
        "modules.ingestion.transport.http.wordpress_webhook_router.decrypt_text",
        return_value="db-secret",
    ) as decrypt:
        result = _resolve_expected_secret(
            uow=uow,
            site_id="site-a",
            env_site_secrets={"site-a": "env-secret"},
            logger=logging.getLogger("test"),
        )

    assert result == "db-secret"
    decrypt.assert_called_once_with(b"<encrypted-blob>")
    assert uow.ingestion.sources.calls == [("wordpress", "site-a")]
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_resolve_falls_back_to_env_when_record_lacks_secret(caplog) -> None:
    record = _record_with_secret(None)
    uow = _uow_with(record)
    caplog.set_level(logging.WARNING)

    result = _resolve_expected_secret(
        uow=uow,
        site_id="site-a",
        env_site_secrets={"site-a": "env-secret"},
        logger=logging.getLogger("test"),
    )

    assert result == "env-secret"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "legacy env secret" in warnings[0].getMessage()
    assert "site-a" in warnings[0].getMessage()


def test_resolve_returns_none_when_no_db_and_no_env(caplog) -> None:
    uow = _uow_with(None)
    caplog.set_level(logging.WARNING)

    result = _resolve_expected_secret(
        uow=uow,
        site_id="site-a",
        env_site_secrets={},
        logger=logging.getLogger("test"),
    )

    assert result is None
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_resolve_returns_env_when_no_db_row_but_env_has_secret(caplog) -> None:
    uow = _uow_with(None)
    caplog.set_level(logging.WARNING)

    result = _resolve_expected_secret(
        uow=uow,
        site_id="legacy-site",
        env_site_secrets={"legacy-site": "env-secret"},
        logger=logging.getLogger("test"),
    )

    assert result == "env-secret"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "legacy-site" in warnings[0].getMessage()
