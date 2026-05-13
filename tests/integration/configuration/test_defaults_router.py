"""Integration tests for the configuration defaults router."""

from __future__ import annotations

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


def test_defaults_get_returns_baseline_when_no_record_exists() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/defaults",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["agency_id"] == seeded.agency_id
            assert payload["defaults"]["duration_seconds"] == 30
            assert "instagram" in payload["defaults"]["platforms"]
            assert "pinterest" in payload["defaults"]["platforms"]


def test_defaults_put_persists_platforms_and_settings() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/defaults",
                json={
                    "platforms": ["instagram", "tiktok"],
                    "duration_seconds": 45,
                    "settings": {"currency": "EUR", "language": "en-IE"},
                },
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                saved = uow.configuration.defaults.get(seeded.agency_id)
            assert saved is not None
            assert list(saved.platforms) == ["instagram", "tiktok"]
            assert saved.duration_seconds == 45
            assert saved.settings == {"currency": "EUR", "language": "en-IE"}


def test_defaults_put_merges_settings_with_existing() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/defaults",
                json={"settings": {"currency": "EUR", "language": "en-IE"}},
                headers=ADMIN_BEARER,
            )
            client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/defaults",
                json={"settings": {"language": "es-ES", "subFont": "Roboto"}},
                headers=ADMIN_BEARER,
            )

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                saved = uow.configuration.defaults.get(seeded.agency_id)
            assert saved is not None
            assert saved.settings == {
                "currency": "EUR",
                "language": "es-ES",
                "subFont": "Roboto",
            }


def test_defaults_put_persists_namespaced_automation_settings() -> None:
    """Defaults `settings` is the canonical bucket for the 7 automation orphans.

    The user-side decision for feature 6 is to relocate the orphan automation
    toggles (publish_mode, review_window_*, quiet_hours_*, skip_weekends,
    auto_captions, regen_on_update, review_emails) to `defaults.settings`
    using namespaced keys (e.g. `automation.quietHoursEnabled`). This test
    documents the contract the front will rely on: arbitrary string keys
    inside `settings` round-trip through the jsonb column verbatim.
    """
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/defaults",
                json={
                    "platforms": ["instagram", "tiktok"],
                    "settings": {
                        "automation.quietHoursEnabled": True,
                        "automation.skipWeekends": False,
                        "automation.autoCaptions": True,
                        "automation.regenOnUpdate": False,
                        "automation.reviewWindowEnabled": True,
                        "automation.reviewWindowHours": 24,
                        "automation.reviewEmails": ["ops@4pm.ie"],
                    },
                },
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                saved = uow.configuration.defaults.get(seeded.agency_id)
            assert saved is not None
            assert list(saved.platforms) == ["instagram", "tiktok"]
            assert saved.settings == {
                "automation.quietHoursEnabled": True,
                "automation.skipWeekends": False,
                "automation.autoCaptions": True,
                "automation.regenOnUpdate": False,
                "automation.reviewWindowEnabled": True,
                "automation.reviewWindowHours": 24,
                "automation.reviewEmails": ["ops@4pm.ie"],
            }


def test_defaults_returns_404_for_unknown_agency() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.get(
                "/v1/admin/agencies/missing/defaults", headers=ADMIN_BEARER
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_AGENCY_NOT_FOUND"
