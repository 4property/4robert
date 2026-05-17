"""Integration tests for feature 32 — paginated, filterable reels listing.

Seeds a fleet of reels for one agency through the existing
``seed_property_with_reel`` helper and exercises the new query params
``page``, ``page_size``, ``workflow_state``, ``publish_status``, ``q`` and
the legacy ``limit`` shim against the real admin reels router.
"""

from __future__ import annotations

from settings import DATABASE_URL
from tests.integration.reels._client import (
    ADMIN_BEARER,
    build_admin_reels_client,
    seed_property_with_reel,
)
from tests.support.postgres import (
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)

_TOTAL_REELS = 50


def _seed_fleet(
    database_url: str,
    *,
    agency_id: str,
    ingestion_source_id: str,
    external_source_id: str,
    total: int = _TOTAL_REELS,
) -> None:
    """Seed ``total`` reels owned by ``agency_id``.

    The fleet is intentionally heterogeneous so the filter tests can
    discriminate by ``workflow_state`` / ``publish_status`` / ``q`` without
    needing dedicated fixtures:

    - 12 reels in ``workflow_state='needs_approval'`` /
      ``publish_status='needs-approval'``.
    - 18 reels in ``workflow_state='approved'`` /
      ``publish_status='pending_publish'``.
    - The rest stay on the helper defaults
      (``workflow_state='rendered'`` / ``publish_status='ready_to_publish'``).

    A subset carries the search needle ``cranford`` in different columns
    so the ``q`` test can verify the three-column ILIKE.
    """
    for index in range(total):
        if index < 12:
            workflow_state = "needs_approval"
            publish_status = "needs-approval"
        elif index < 30:
            workflow_state = "approved"
            publish_status = "pending_publish"
        else:
            workflow_state = "rendered"
            publish_status = "ready_to_publish"

        # Distribute the ``cranford`` needle across the three columns the
        # ``q`` filter must inspect. The remaining rows carry neutral
        # strings so the assertions can pin the exact count.
        if index == 5:
            title = "The Cranford Estate"
            slug = f"reel-{index:03d}"
            list_reference = "REF-123"
        elif index == 6:
            title = "Test Property"
            slug = f"cranford-{index:03d}"
            list_reference = "REF-456"
        elif index == 7:
            title = "Another Property"
            slug = f"reel-{index:03d}"
            list_reference = "CRANFORD-REF-789"
        else:
            title = f"Property {index:03d}"
            slug = f"reel-{index:03d}"
            list_reference = f"REF-{index:03d}"

        seed_property_with_reel(
            database_url,
            agency_id=agency_id,
            ingestion_source_id=ingestion_source_id,
            external_source_id=external_source_id,
            source_property_id=1000 + index,
            workflow_state=workflow_state,
            publish_status=publish_status,
            slug=slug,
            title=title,
            list_reference=list_reference,
        )


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_first_page_returns_page_size_items_and_has_more() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_fleet(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels"
                "?page=1&page_size=10",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert len(payload["items"]) == 10
            assert payload["count"] == 10  # legacy alias for len(items)
            assert payload["count_total"] == _TOTAL_REELS
            assert payload["page"] == 1
            assert payload["page_size"] == 10
            assert payload["has_more"] is True


def test_last_page_returns_remaining_items_and_has_more_false() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_fleet(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels"
                "?page=5&page_size=10",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert len(payload["items"]) == 10
            assert payload["count"] == 10
            assert payload["count_total"] == _TOTAL_REELS
            assert payload["page"] == 5
            assert payload["page_size"] == 10
            assert payload["has_more"] is False


def test_beyond_last_page_returns_no_items_but_count_total_intact() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_fleet(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels"
                "?page=6&page_size=10",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["items"] == []
            assert payload["count"] == 0
            assert payload["count_total"] == _TOTAL_REELS
            assert payload["has_more"] is False


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def test_workflow_state_filter_narrows_results() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_fleet(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels"
                "?workflow_state=needs_approval&page_size=50",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["count_total"] == 12
            assert all(
                item["workflow_state"] == "needs_approval"
                for item in payload["items"]
            )


def test_workflow_state_filter_accepts_csv() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_fleet(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels"
                "?workflow_state=needs_approval,approved&page_size=50",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["count_total"] == 30  # 12 needs_approval + 18 approved
            assert {item["workflow_state"] for item in payload["items"]} <= {
                "needs_approval",
                "approved",
            }


def test_unknown_workflow_state_returns_422() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_fleet(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels"
                "?workflow_state=bogus_state",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 422
            body = response.json()
            assert body["code"] == "INVALID_FILTER_VALUE"


def test_publish_status_filter_combines_with_workflow_state() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_fleet(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            # publish_status alone: 12 with needs-approval, 18 with
            # pending_publish, 20 with ready_to_publish.
            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels"
                "?publish_status=pending_publish&page_size=50",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            assert response.json()["count_total"] == 18

            # Combined with workflow_state — the AND of the two filters
            # is what the user gets: pending_publish AND approved -> 18.
            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels"
                "?publish_status=pending_publish&workflow_state=approved"
                "&page_size=50",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["count_total"] == 18
            assert all(
                item["workflow_state"] == "approved"
                and item["publish_status"] == "pending_publish"
                for item in payload["items"]
            )

            # Combined but contradictory — needs_approval reels never
            # carry pending_publish so the slice is empty.
            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels"
                "?publish_status=pending_publish&workflow_state=needs_approval"
                "&page_size=50",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["count_total"] == 0
            assert payload["items"] == []


def test_q_matches_title_slug_or_property_reference() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_fleet(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels"
                "?q=cranford&page_size=50",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            # 3 needles: 1 in title, 1 in slug, 1 in list_reference.
            assert payload["count_total"] == 3
            property_ids = {item["source_property_id"] for item in payload["items"]}
            assert property_ids == {1005, 1006, 1007}


def test_count_total_reflects_active_filters() -> None:
    """A filtered listing must not echo back the unfiltered agency count."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_fleet(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels"
                "?workflow_state=needs_approval&page_size=5",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["count_total"] == 12
            assert payload["count_total"] != _TOTAL_REELS
            assert len(payload["items"]) == 5
            assert payload["has_more"] is True


# ---------------------------------------------------------------------------
# Backwards compatibility + clamping
# ---------------------------------------------------------------------------


def test_legacy_limit_query_param_still_works() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_fleet(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels?limit=10",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert len(payload["items"]) == 10
            assert payload["count"] == 10
            assert payload["count_total"] == _TOTAL_REELS
            assert payload["page"] == 1
            assert payload["page_size"] == 10
            assert payload["has_more"] is True


def test_page_size_clamps_to_max_when_too_large() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_fleet(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels?page_size=500",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["page_size"] == 100
            # Only 50 seeded rows so the slice never reaches the clamped
            # cap, but ``page_size`` itself must echo back the clamped
            # value so the frontend pager renders correctly.
            assert len(payload["items"]) == _TOTAL_REELS


def test_page_zero_clamps_to_one() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_fleet(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels"
                "?page=0&page_size=5",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["page"] == 1
            assert len(payload["items"]) == 5


def test_blank_q_is_treated_as_no_filter() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_fleet(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels"
                "?q=%20%20%20&page_size=10",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["count_total"] == _TOTAL_REELS


def test_page_size_query_wins_over_legacy_limit() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_fleet(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels"
                "?limit=99&page_size=5",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["page_size"] == 5
            assert len(payload["items"]) == 5
