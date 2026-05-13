"""Integration tests for agency render-template selection."""

from __future__ import annotations

import json

from sqlalchemy import create_engine, text

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


def test_render_templates_list_returns_seeded_classic() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/render-templates",
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["agency_id"] == seeded.agency_id
            assert payload["current_template_id"] == "classic"
            classic = payload["items"][0]
            assert classic["template_id"] == "classic"
            assert classic["display_name"] == "Classic"
            assert classic["preview_images"] == []
            assert classic["layout_variant"] == "classic"
            assert classic["selected"] is True


def test_render_templates_list_includes_side_banner() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/render-templates",
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 200, response.text
            payload = response.json()
            items_by_id = {item["template_id"]: item for item in payload["items"]}
            assert "classic" in items_by_id
            assert "side_banner" in items_by_id

            side_banner = items_by_id["side_banner"]
            assert side_banner["display_name"] == "Side Banner"
            assert side_banner["status"] == "active"
            assert side_banner["sort_order"] == 1
            assert side_banner["layout_variant"] == "side_banner"
            # Classic is the default selection on a fresh agency.
            assert items_by_id["classic"]["sort_order"] == 0
            assert items_by_id["classic"]["selected"] is True
            assert side_banner["selected"] is False


def test_render_template_select_persists_side_banner_on_defaults() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            defaults_response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/defaults",
                json={"render_template_id": "side_banner"},
                headers=ADMIN_BEARER,
            )

            assert defaults_response.status_code == 200, defaults_response.text
            assert (
                defaults_response.json()["defaults"]["render_template_id"]
                == "side_banner"
            )

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                defaults = uow.configuration.defaults.get(seeded.agency_id)
            assert defaults is not None
            assert defaults.render_template_id == "side_banner"


def test_render_template_select_persists_on_defaults() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _insert_template(database.url, template_id="compact")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/render-template",
                json={"template_id": "compact"},
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 200, response.text
            assert response.json()["render_template"]["template_id"] == "compact"
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                defaults = uow.configuration.defaults.get(seeded.agency_id)
            assert defaults is not None
            assert defaults.render_template_id == "compact"


def test_render_template_select_rejects_unknown_or_disabled_template() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _insert_template(database.url, template_id="disabled", status="disabled")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            missing = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/render-template",
                json={"template_id": "missing"},
                headers=ADMIN_BEARER,
            )
            disabled = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/render-template",
                json={"template_id": "disabled"},
                headers=ADMIN_BEARER,
            )

            assert missing.status_code == 404
            assert missing.json()["code"] == "RENDER_TEMPLATE_NOT_FOUND"
            assert disabled.status_code == 400
            assert disabled.json()["code"] == "RENDER_TEMPLATE_NOT_SELECTABLE"


def test_defaults_and_reel_profile_round_trip_render_template_id() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _insert_template(database.url, template_id="compact")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            defaults_response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/defaults",
                json={"render_template_id": "compact"},
                headers=ADMIN_BEARER,
            )
            profile_response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reel-profile",
                headers=ADMIN_BEARER,
            )
            profile_update = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/reel-profile",
                json={"render_template_id": "classic"},
                headers=ADMIN_BEARER,
            )

            assert defaults_response.status_code == 200, defaults_response.text
            assert (
                defaults_response.json()["defaults"]["render_template_id"] == "compact"
            )
            assert profile_response.status_code == 200, profile_response.text
            assert (
                profile_response.json()["reel_profile"]["render_template_id"]
                == "compact"
            )
            assert profile_update.status_code == 200, profile_update.text
            assert (
                profile_update.json()["reel_profile"]["render_template_id"]
                == "classic"
            )


def _insert_template(
    database_url: str,
    *,
    template_id: str,
    status: str = "active",
) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO render_templates ("
                    "template_id, display_name, description, status, sort_order, "
                    "preview_images, layout_variant, reel_settings, poster_settings, "
                    "created_at, updated_at"
                    ") VALUES ("
                    ":template_id, :display_name, '', :status, 10, "
                    "CAST(:preview_images AS jsonb), 'classic', "
                    "CAST(:reel_settings AS jsonb), CAST(:poster_settings AS jsonb), "
                    "timezone('utc', now()), timezone('utc', now())"
                    ")"
                ),
                {
                    "template_id": template_id,
                    "display_name": template_id.title(),
                    "status": status,
                    "preview_images": json.dumps(
                        [
                            {
                                "kind": "thumbnail",
                                "image_url": f"https://cdn.example/{template_id}.jpg",
                                "alt": f"{template_id} preview",
                            }
                        ]
                    ),
                    "reel_settings": json.dumps({"width": 720}),
                    "poster_settings": json.dumps({"width": 900}),
                },
            )
    finally:
        engine.dispose()
