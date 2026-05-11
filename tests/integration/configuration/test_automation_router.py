"""Integration tests for the configuration automation router."""

from __future__ import annotations

import pytest

from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.integration.configuration._client import (
    ADMIN_BEARER,
    build_configuration_client,
)
from tests.support.postgres import (
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


def test_automation_get_returns_baseline_when_no_record_exists() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/automation",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["agency_id"] == seeded.agency_id
            assert payload["automation"]["approval_required"] is False


def test_automation_put_persists_typed_record() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/automation",
                json={
                    "approval_required": True,
                    "publish_window_start": "09:00",
                    "publish_window_end": "20:00",
                    "publish_days": ["mon", "tue", "wed"],
                    "trigger_on_status": ["for_sale"],
                },
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                saved = uow.configuration.automation.get(seeded.agency_id)
            assert saved is not None
            assert saved.approval_required is True
            assert saved.publish_window_start == "09:00"
            assert list(saved.publish_days) == ["mon", "tue", "wed"]
            assert list(saved.trigger_on_status) == ["for_sale"]


def test_automation_put_rejects_platforms_field() -> None:
    """Platforms is owned by /defaults — automation must reject it."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/automation",
                json={
                    "approval_required": True,
                    "platforms": ["instagram"],
                },
                headers=ADMIN_BEARER,
            )
            # `extra="forbid"` returns a 422 Pydantic validation error.
            assert response.status_code == 422


def test_automation_returns_404_for_unknown_agency() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.get(
                "/v1/admin/agencies/missing/automation", headers=ADMIN_BEARER
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_AGENCY_NOT_FOUND"


@pytest.mark.parametrize(
    "legacy_key,legacy_value",
    [
        ("publish_mode", "review"),
        ("review_window_enabled", True),
        ("review_window_hours", 24),
        ("quiet_hours_enabled", True),
        ("skip_weekends", True),
        ("auto_captions", True),
        ("regen_on_update", False),
        ("review_emails", ["ops@4pm.ie"]),
    ],
)
def test_automation_put_rejects_legacy_keys(
    legacy_key: str, legacy_value: object
) -> None:
    """Automation PUT must reject legacy frontend keys via `extra='forbid'`.

    Documents the canonical Automation contract: only `approval_required`,
    `publish_window_start`, `publish_window_end`, `publish_days`,
    `trigger_on_status` are accepted. The user-side decision is to relocate
    the 7 orphan toggles (publish_mode, review_window_*, quiet_hours_*,
    skip_weekends, auto_captions, regen_on_update, review_emails) to
    `defaults.settings` with namespaced keys (front-side change).
    """
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/automation",
                json={
                    "approval_required": True,
                    legacy_key: legacy_value,
                },
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 422, response.text
            assert legacy_key in response.text
