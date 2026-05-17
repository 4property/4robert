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


def test_social_templates_put_rejects_unknown_variable_with_422() -> None:
    """An unknown `{{variable}}` must produce a 422 instead of silently
    persisting a template that publishes a literal `{{cosa_inventada}}` to
    the network.
    """
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
                        "instagram": "Visit {{cosa_inventada}} in {{city}}",
                    }
                },
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 422, response.text
            body = response.json()
            assert body["code"] == "SOCIAL_TEMPLATE_UNKNOWN_VARIABLE"
            assert "cosa_inventada" in body["error"]
            details = body.get("details") or {}
            assert details.get("unknown_variables_by_platform") == {
                "instagram": ["cosa_inventada"]
            }
            assert "property_title" in details.get("allowed_variables", [])

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                stored = uow.configuration.social_templates.list_for_agency(
                    seeded.agency_id
                )
            assert stored == ()


def test_social_templates_put_accepts_allowed_variables_only() -> None:
    """A template that references only allowed variables must succeed."""
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
                        "instagram": (
                            "{{property_title}} - {{price}}\n"
                            "{{short_description}}\n{{booking_link}}"
                        ),
                        "tiktok": "Just listed in {{neighborhood}} - {{property_title}}",
                    }
                },
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["status"] == "saved"
            assert set(payload["templates"].keys()) == {"instagram", "tiktok"}


def test_social_templates_put_accepts_template_without_any_variables() -> None:
    """Plain strings with no `{{...}}` references must remain accepted
    (regression: the validator only enforces the catalog when a variable is
    actually referenced, otherwise free copy stays legal).
    """
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
                        "instagram": "static caption, no variables, no placeholders",
                        "facebook": "",
                    }
                },
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 200, response.text


def test_social_templates_put_accepts_literal_braces_that_do_not_form_a_variable() -> None:
    """Stray `{{` or `}}` (or `{{ }}`) without a captured name must not
    trigger validation. The regex requires `{{ <word> }}`; anything else is
    free-form text the user can keep using.
    """
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
                        "instagram": "open {{ unclosed and }} stray with {{ }} empty",
                        "tiktok": "{{ has space inside }} should not match",
                    }
                },
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 200, response.text


def test_social_templates_put_reports_every_offending_platform() -> None:
    """When several platforms reference unknown variables the 422 payload
    must enumerate them all so the admin fixes them in one round-trip.
    """
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
                        "instagram": "{{foo}} {{property_title}}",
                        "tiktok": "{{bar}} {{baz}}",
                        "facebook": "{{property_title}}",
                    }
                },
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 422, response.text
            body = response.json()
            assert body["code"] == "SOCIAL_TEMPLATE_UNKNOWN_VARIABLE"
            details = body.get("details") or {}
            offending = details.get("unknown_variables_by_platform") or {}
            assert offending == {"instagram": ["foo"], "tiktok": ["bar", "baz"]}


# ── Feature 20 — rich payload, title_template & hashtags ────────────────────


def test_put_accepts_rich_shape_with_title_and_hashtags() -> None:
    """Feature 20: the PUT accepts ``{description_template, title_template,
    hashtags}`` per platform and the GET surfaces them in ``items[]``.
    """
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
                        "pinterest": {
                            "description_template": "See {{property_title}} in {{city}}",
                            "title_template": "{{property_title}} · {{price}}",
                            "hashtags": ["#realestate", "#dublin"],
                        }
                    }
                },
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 200, response.text
            payload = response.json()
            # Legacy flat `templates` keeps the description for backward-compat.
            assert payload["templates"] == {
                "pinterest": "See {{property_title}} in {{city}}",
            }
            items_by_platform = {item["platform"]: item for item in payload["items"]}
            assert items_by_platform["pinterest"]["title_template"] == (
                "{{property_title}} · {{price}}"
            )
            assert items_by_platform["pinterest"]["hashtags"] == [
                "#realestate",
                "#dublin",
            ]

            # GET round-trip exposes the rich fields too.
            get_response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/social-templates",
                headers=ADMIN_BEARER,
            )
            assert get_response.status_code == 200, get_response.text
            get_body = get_response.json()
            stored = {item["platform"]: item for item in get_body["items"]}
            assert stored["pinterest"]["description_template"] == (
                "See {{property_title}} in {{city}}"
            )
            assert stored["pinterest"]["title_template"] == (
                "{{property_title}} · {{price}}"
            )
            assert stored["pinterest"]["hashtags"] == ["#realestate", "#dublin"]


def test_put_rejects_unknown_variable_in_title_template_with_422() -> None:
    """Title template variables are validated against the same catalog as
    descriptions. The 422 payload nests ``title_template`` under the
    platform so the frontend renders the error next to the right field.
    """
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
                        "pinterest": {
                            "description_template": "{{property_title}}",
                            "title_template": "{{cosa_inventada}} of {{city}}",
                            "hashtags": [],
                        }
                    }
                },
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 422, response.text
            body = response.json()
            assert body["code"] == "SOCIAL_TEMPLATE_UNKNOWN_VARIABLE"
            details = body.get("details") or {}
            assert details["unknown_variables_by_platform"] == {
                "pinterest": {"title_template": ["cosa_inventada"]},
            }


def test_put_reports_both_fields_when_each_has_unknown_variables() -> None:
    """If both description and title carry unknown variables, the nested
    shape lists both keys so the admin fixes them in one round-trip.
    """
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
                        "pinterest": {
                            "description_template": "{{foo}} home in {{city}}",
                            "title_template": "{{bar}}",
                            "hashtags": [],
                        }
                    }
                },
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 422, response.text
            details = response.json().get("details") or {}
            assert details["unknown_variables_by_platform"] == {
                "pinterest": {
                    "description_template": ["foo"],
                    "title_template": ["bar"],
                }
            }


def test_put_rejects_invalid_hashtag_with_422() -> None:
    """Each hashtag must match ``^#[\\w-]{1,50}$``; otherwise 422."""
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
                        "pinterest": {
                            "description_template": "",
                            "title_template": "",
                            "hashtags": ["#valid", "no-hash", "#bad space"],
                        }
                    }
                },
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 422, response.text
            body = response.json()
            assert body["code"] == "SOCIAL_TEMPLATE_INVALID_HASHTAG"
            details = body.get("details") or {}
            errors = details.get("hashtag_errors_by_platform") or {}
            assert errors == {
                "pinterest": {"invalid": ["no-hash", "#bad space"]}
            }


def test_put_rejects_more_than_30_hashtags_with_422() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            hashtags = [f"#tag{i:03d}" for i in range(35)]
            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/social-templates",
                json={
                    "templates": {
                        "instagram": {
                            "description_template": "",
                            "title_template": "",
                            "hashtags": hashtags,
                        }
                    }
                },
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 422, response.text
            body = response.json()
            assert body["code"] == "SOCIAL_TEMPLATE_INVALID_HASHTAG"
            details = body.get("details") or {}
            errors = details.get("hashtag_errors_by_platform") or {}
            assert errors["instagram"]["count"] == 35
            assert errors["instagram"]["max"] == 30


def test_put_legacy_string_shape_still_works() -> None:
    """Backward-compat: ``templates[platform] = "<string>"`` keeps working."""
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
                        "instagram": "Visit {{property_title}} in {{city}}",
                    }
                },
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["templates"] == {
                "instagram": "Visit {{property_title}} in {{city}}",
            }
            items = {item["platform"]: item for item in payload["items"]}
            # title_template and hashtags default to empty for the legacy shape.
            assert items["instagram"]["title_template"] == ""
            assert items["instagram"]["hashtags"] == []
