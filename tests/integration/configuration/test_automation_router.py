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
        ("auto_captions", True),
        ("regen_on_update", False),
        ("review_emails", ["ops@4pm.ie"]),
    ],
)
def test_automation_put_rejects_legacy_keys(
    legacy_key: str, legacy_value: object
) -> None:
    """Automation PUT must reject legacy frontend keys via `extra='forbid'`.

    Documents the canonical Automation contract: only the typed columns of
    ``agency_automation_rules`` plus the feature-13 toggles
    (``hold_window_seconds``, ``quiet_hours_enabled``, ``skip_weekends``)
    are accepted. The remaining orphan toggles (publish_mode,
    review_window_*, auto_captions, regen_on_update, review_emails) live in
    ``defaults.settings`` with namespaced keys (front-side change).
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


def test_automation_put_round_trips_hold_quiet_skip() -> None:
    """Feature 13: PUT the three new fields and verify a follow-up GET
    returns them exactly. Then confirm the repository persisted them by
    re-reading via the UoW."""

    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            put_response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/automation",
                json={
                    "approval_required": True,
                    "publish_window_start": "09:00",
                    "publish_window_end": "20:00",
                    "publish_days": ["mon", "tue", "wed"],
                    "trigger_on_status": ["for_sale"],
                    "hold_window_seconds": 1800,
                    "quiet_hours_enabled": True,
                    "skip_weekends": True,
                },
                headers=ADMIN_BEARER,
            )
            assert put_response.status_code == 200, put_response.text
            put_payload = put_response.json()["automation"]
            assert put_payload["hold_window_seconds"] == 1800
            assert put_payload["quiet_hours_enabled"] is True
            assert put_payload["skip_weekends"] is True

            get_response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/automation",
                headers=ADMIN_BEARER,
            )
            assert get_response.status_code == 200, get_response.text
            get_payload = get_response.json()["automation"]
            assert get_payload["hold_window_seconds"] == 1800
            assert get_payload["quiet_hours_enabled"] is True
            assert get_payload["skip_weekends"] is True

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                saved = uow.configuration.automation.get(seeded.agency_id)
            assert saved is not None
            assert saved.hold_window_seconds == 1800
            assert saved.quiet_hours_enabled is True
            assert saved.skip_weekends is True


def test_automation_put_preserves_hold_quiet_skip_when_omitted() -> None:
    """Feature 13: a second PUT that omits the new fields must preserve
    the previously stored values (defaults only apply on the initial
    INSERT, not on every UPDATE)."""

    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            first = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/automation",
                json={
                    "approval_required": True,
                    "hold_window_seconds": 7200,
                    "quiet_hours_enabled": True,
                    "skip_weekends": True,
                },
                headers=ADMIN_BEARER,
            )
            assert first.status_code == 200, first.text

            # Second PUT changes only `approval_required`; the three
            # feature-13 fields are absent and must not flip back to
            # defaults.
            second = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/automation",
                json={"approval_required": False},
                headers=ADMIN_BEARER,
            )
            assert second.status_code == 200, second.text
            second_payload = second.json()["automation"]
            assert second_payload["approval_required"] is False
            assert second_payload["hold_window_seconds"] == 7200
            assert second_payload["quiet_hours_enabled"] is True
            assert second_payload["skip_weekends"] is True


def test_automation_put_rejects_hold_window_out_of_range() -> None:
    """`hold_window_seconds` must be in [0, 86400] (clamped to 24h)."""

    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            negative = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/automation",
                json={"hold_window_seconds": -1},
                headers=ADMIN_BEARER,
            )
            assert negative.status_code == 422, negative.text

            too_large = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/automation",
                json={"hold_window_seconds": 86401},
                headers=ADMIN_BEARER,
            )
            assert too_large.status_code == 422, too_large.text
