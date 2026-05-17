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


def test_defaults_put_persists_music_selection_rules_false() -> None:
    """Feature 24: PUT with `fallback_to_full_library=false` round-trips."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/defaults",
                json={
                    "settings": {
                        "music": {
                            "selection_rules": {
                                "fallback_to_full_library": False,
                            }
                        }
                    }
                },
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            put_payload = response.json()
            assert (
                put_payload["defaults"]["settings"]["music"][
                    "selection_rules"
                ]["fallback_to_full_library"]
                is False
            )

            get_response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/defaults",
                headers=ADMIN_BEARER,
            )
            assert get_response.status_code == 200, get_response.text
            get_payload = get_response.json()
            assert (
                get_payload["defaults"]["settings"]["music"][
                    "selection_rules"
                ]["fallback_to_full_library"]
                is False
            )

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                saved = uow.configuration.defaults.get(seeded.agency_id)
            assert saved is not None
            assert saved.settings == {
                "music": {
                    "selection_rules": {
                        "fallback_to_full_library": False,
                    }
                }
            }


def test_defaults_put_persists_music_selection_rules_true() -> None:
    """Feature 24: PUT with `fallback_to_full_library=true` round-trips."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/defaults",
                json={
                    "settings": {
                        "music": {
                            "selection_rules": {
                                "fallback_to_full_library": True,
                            }
                        }
                    }
                },
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            assert (
                response.json()["defaults"]["settings"]["music"][
                    "selection_rules"
                ]["fallback_to_full_library"]
                is True
            )


def test_defaults_put_rejects_unknown_music_key() -> None:
    """Feature 24: unknown keys under `music.*` are rejected with 422."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/defaults",
                json={"settings": {"music": {"unknown_key": True}}},
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 422, response.text


def test_defaults_put_rejects_unknown_selection_rules_key() -> None:
    """Feature 24: unknown keys under `music.selection_rules.*` → 422."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/defaults",
                json={
                    "settings": {
                        "music": {
                            "selection_rules": {"unknown_key": True}
                        }
                    }
                },
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 422, response.text


def test_defaults_get_surfaces_music_selection_rules_default() -> None:
    """Feature 24: GET surfaces the default `fallback_to_full_library=true`.

    PUTting a payload without `settings.music` must not persist the
    default into the JSONB column (the absence is preserved). The GET
    response, however, fills it in so the frontend Toggle starts with
    a defined value.
    """
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/defaults",
                json={"settings": {"currency": "EUR"}},
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text

            get_response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/defaults",
                headers=ADMIN_BEARER,
            )
            assert get_response.status_code == 200, get_response.text
            settings_block = get_response.json()["defaults"]["settings"]
            assert (
                settings_block["music"]["selection_rules"][
                    "fallback_to_full_library"
                ]
                is True
            )

            # The absence is preserved in the persisted JSONB column so
            # the DB never accumulates implicit state.
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                saved = uow.configuration.defaults.get(seeded.agency_id)
            assert saved is not None
            assert "music" not in saved.settings


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
