"""Integration test for `IngestPropertyIntoReelUseCase` against Postgres."""

from __future__ import annotations

from sqlalchemy import create_engine, text

from modules.reels.domain.types import PropertyMediaJob
from modules.tenancy.domain.context import TenantContext
from modules.reels.application.use_cases.ingest_property_into_reel import (
    IngestPropertyIntoReelUseCase,
)
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.support.postgres import (
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


_PAYLOAD = {
    "id": 42,
    "slug": "casa-bonita",
    "title": {"rendered": "Casa Bonita"},
    "link": "https://ckp.ie/casa-bonita",
    "property_status": "for sale",
    "price": "275000",
    "wppd_pics": ["https://ckp.ie/img1.jpg"],
}


def _build_job(*, agency_id: str, ingestion_source_id: str, site_id: str) -> PropertyMediaJob:
    tenant = TenantContext(
        site_id=site_id,
        agency_id=agency_id,
        wordpress_source_id=ingestion_source_id,
    )
    return PropertyMediaJob(
        event_id="event-1",
        tenant=tenant,
        property_id=42,
        received_at="2026-05-02T10:00:00+00:00",
        raw_payload_hash="hash-1",
        payload=_PAYLOAD,
        publish_context=None,
        job_id="job-1",
    )


def test_execute_persists_reel_state_and_property_on_postgres() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            use_case = IngestPropertyIntoReelUseCase(
                workspace_dir=workspace_dir,
                property_url_template="",
                property_url_tracking_params=None,
                social_publishing_enabled=False,
                database_locator=database.url,
            )
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                context = use_case.execute(
                    _build_job(
                        agency_id=seeded.agency_id,
                        ingestion_source_id=seeded.ingestion_source_id,
                        site_id=seeded.external_source_id,
                    ),
                    uow=uow,
                )

            assert context.requires_render is True
            assert context.is_noop is False

            engine = create_engine(database.url, future=True)
            try:
                with engine.connect() as connection:
                    reel_row = connection.execute(
                        text(
                            "SELECT workflow_state, render_status, publish_status, "
                            "agency_id, ingestion_source_id, content_snapshot, "
                            "publish_target_snapshot "
                            "FROM reels WHERE external_source_id = :site_id "
                            "AND source_property_id = :pid"
                        ),
                        {"site_id": seeded.external_source_id, "pid": 42},
                    ).first()
                    assert reel_row is not None
                    assert reel_row.workflow_state == "ingested"
                    assert reel_row.render_status == "pending"
                    assert reel_row.publish_status == "skipped"
                    assert reel_row.agency_id == seeded.agency_id
                    assert reel_row.ingestion_source_id == seeded.ingestion_source_id
                    # JSONB columns return native dicts (psycopg native typing).
                    assert isinstance(reel_row.content_snapshot, dict)
                    assert isinstance(reel_row.publish_target_snapshot, dict)
                    assert reel_row.content_snapshot["delivery_plan"]["listing_lifecycle"] == "for_sale"

                    property_row = connection.execute(
                        text(
                            "SELECT agency_id, ingestion_source_id, slug, title "
                            "FROM properties WHERE external_source_id = :site_id "
                            "AND source_property_id = :pid"
                        ),
                        {"site_id": seeded.external_source_id, "pid": 42},
                    ).first()
                    assert property_row is not None
                    assert property_row.agency_id == seeded.agency_id
                    assert property_row.ingestion_source_id == seeded.ingestion_source_id
                    assert property_row.slug == "casa-bonita"

                    revision_count = connection.execute(
                        text("SELECT COUNT(*) FROM media_revisions")
                    ).scalar()
                    # The ingest step does not write to media_revisions; the
                    # publisher step (feature 13) is the only writer.
                    assert revision_count == 0
            finally:
                engine.dispose()
