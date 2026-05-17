"""Guards the ordering contract of the reels list endpoint.

`GET /v1/admin/agencies/{agency_id}/reels` must return rows sorted by
`r.updated_at DESC NULLS LAST` (see
`modules/reels/infrastructure/reel_query.py:259`). A reel whose
`updated_at` is bumped must surface at the top on the next GET. The
backend already enforces this contract today; this file is a regression
guard.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text

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


def _force_updated_at(
    database_url: str,
    *,
    external_source_id: str,
    source_property_id: int,
    when: datetime,
) -> None:
    """Pin a reel's ``updated_at`` to a fixed timestamp via direct SQL.

    The normal seed path uses ``now()`` for every row, so without this
    helper every reel ends up with effectively identical timestamps and
    the ordering assertion becomes flaky / meaningless.
    """
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE reels SET updated_at = :when "
                    "WHERE external_source_id = :external_source_id "
                    "AND source_property_id = :source_property_id"
                ),
                {
                    "when": when,
                    "external_source_id": external_source_id,
                    "source_property_id": source_property_id,
                },
            )
    finally:
        engine.dispose()


def test_list_reels_orders_by_updated_at_desc() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")

            t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
            reel_a_pid = 2001
            reel_b_pid = 2002
            reel_c_pid = 2003

            for pid in (reel_a_pid, reel_b_pid, reel_c_pid):
                seed_property_with_reel(
                    database.url,
                    agency_id=seeded.agency_id,
                    ingestion_source_id=seeded.ingestion_source_id,
                    external_source_id=seeded.external_source_id,
                    source_property_id=pid,
                    slug=f"reel-{pid}",
                    title=f"Property {pid}",
                )

            _force_updated_at(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=reel_a_pid,
                when=t0,
            )
            _force_updated_at(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=reel_b_pid,
                when=t0 + timedelta(hours=1),
            )
            _force_updated_at(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=reel_c_pid,
                when=t0 + timedelta(hours=2),
            )

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels?page_size=50",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            observed_pids = [
                item["source_property_id"] for item in payload["items"]
            ]
            assert observed_pids == [reel_c_pid, reel_b_pid, reel_a_pid]


def test_list_reels_promotes_touched_reel_to_top() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")

            t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
            reel_a_pid = 2001
            reel_b_pid = 2002
            reel_c_pid = 2003

            for pid in (reel_a_pid, reel_b_pid, reel_c_pid):
                seed_property_with_reel(
                    database.url,
                    agency_id=seeded.agency_id,
                    ingestion_source_id=seeded.ingestion_source_id,
                    external_source_id=seeded.external_source_id,
                    source_property_id=pid,
                    slug=f"reel-{pid}",
                    title=f"Property {pid}",
                )

            _force_updated_at(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=reel_a_pid,
                when=t0,
            )
            _force_updated_at(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=reel_b_pid,
                when=t0 + timedelta(hours=1),
            )
            _force_updated_at(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=reel_c_pid,
                when=t0 + timedelta(hours=2),
            )

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            initial_response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels?page_size=50",
                headers=ADMIN_BEARER,
            )
            assert initial_response.status_code == 200
            initial_pids = [
                item["source_property_id"]
                for item in initial_response.json()["items"]
            ]
            assert initial_pids == [reel_c_pid, reel_b_pid, reel_a_pid]

            # Touch the oldest reel: its updated_at jumps past every
            # other row, so the next GET must surface it first.
            _force_updated_at(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=reel_a_pid,
                when=t0 + timedelta(hours=3),
            )

            promoted_response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels?page_size=50",
                headers=ADMIN_BEARER,
            )
            assert promoted_response.status_code == 200
            promoted_pids = [
                item["source_property_id"]
                for item in promoted_response.json()["items"]
            ]
            assert promoted_pids == [reel_a_pid, reel_c_pid, reel_b_pid]
