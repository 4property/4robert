"""Integration tests for the configuration social-templates router."""

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


def test_social_templates_get_returns_empty_when_none_stored() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/social-templates",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["templates"] == {}
            assert payload["count"] == 0


def test_social_templates_put_persists_per_platform_rows() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/social-templates",
                json={
                    "templates": {
                        "Instagram": "ig template",
                        " TikTok ": "tt template",
                    }
                },
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["templates"] == {
                "instagram": "ig template",
                "tiktok": "tt template",
            }

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                saved = uow.configuration.social_templates.list_for_agency(
                    seeded.agency_id
                )
            by_platform = {row.platform: row.description_template for row in saved}
            assert by_platform == {
                "instagram": "ig template",
                "tiktok": "tt template",
            }


def test_social_templates_put_replaces_whole_block() -> None:
    """The verb is `replace`: old rows must vanish on each PUT."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/social-templates",
                json={"templates": {"instagram": "ig", "facebook": "fb"}},
                headers=ADMIN_BEARER,
            )
            client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/social-templates",
                json={"templates": {"tiktok": "tt"}},
                headers=ADMIN_BEARER,
            )

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                saved = uow.configuration.social_templates.list_for_agency(
                    seeded.agency_id
                )
            platforms = {row.platform for row in saved}
            assert platforms == {"tiktok"}


def test_social_templates_returns_404_for_unknown_agency() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.get(
                "/v1/admin/agencies/missing/social-templates", headers=ADMIN_BEARER
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_AGENCY_NOT_FOUND"
