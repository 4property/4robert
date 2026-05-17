"""Integration tests for brand-font injection during reel ingestion.

Feature 28: ``IngestPropertyIntoReelUseCase`` must resolve the agency's
``BrandSettings.font_family`` against
:mod:`modules.configuration.domain.font_catalog` and stamp the regular
+ bold TTF paths onto ``render_template_reel_settings`` /
``render_template_poster_settings`` so the downstream renderer wires
ffmpeg ``drawtext`` against the catalogued TTF instead of the
``DEFAULT_REEL_FONT_PATH`` Inter hardcode.
"""

from __future__ import annotations

from modules.configuration.domain import font_catalog
from modules.reels.application.use_cases.ingest_property_into_reel import (
    IngestPropertyIntoReelUseCase,
)
from modules.reels.domain.types import PropertyMediaJob
from modules.tenancy.domain.context import TenantContext
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.support.postgres import (
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


_PAYLOAD = {
    "id": 99,
    "slug": "casa-fontana",
    "title": {"rendered": "Casa Fontana"},
    "link": "https://ckp.ie/casa-fontana",
    "property_status": "for sale",
    "price": "350000",
    "wppd_pics": ["https://ckp.ie/photo-1.jpg"],
}


def _build_job(
    *,
    agency_id: str,
    ingestion_source_id: str,
    site_id: str,
) -> PropertyMediaJob:
    tenant = TenantContext(
        site_id=site_id,
        agency_id=agency_id,
        wordpress_source_id=ingestion_source_id,
    )
    return PropertyMediaJob(
        event_id="event-font",
        tenant=tenant,
        property_id=99,
        received_at="2026-05-14T10:00:00+00:00",
        raw_payload_hash="font-hash",
        payload=_PAYLOAD,
        publish_context=None,
        job_id="job-font",
    )


def _run_ingest_with_brand_font(
    *,
    font_family: str | None,
    database_url: str,
    workspace_dir,
):
    seeded = seed_tenant(database_url, site_id="ckp.ie", workspace_dir=workspace_dir)
    with DatabaseUnitOfWork(database_url, workspace_dir) as uow:
        assert uow.configuration is not None
        if font_family is not None:
            uow.configuration.brand.upsert(
                agency_id=seeded.agency_id, font_family=font_family
            )
    use_case = IngestPropertyIntoReelUseCase(
        workspace_dir=workspace_dir,
        property_url_template="",
        property_url_tracking_params=None,
        social_publishing_enabled=False,
        database_locator=database_url,
    )
    with DatabaseUnitOfWork(database_url, workspace_dir) as uow:
        return use_case.execute(
            _build_job(
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                site_id=seeded.external_source_id,
            ),
            uow=uow,
        )


def test_ingest_injects_manrope_font_paths_when_agency_picked_manrope() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            context = _run_ingest_with_brand_font(
                font_family="Manrope",
                database_url=database.url,
                workspace_dir=workspace_dir,
            )
    descriptor = font_catalog.resolve("Manrope")
    assert context.render_template_reel_settings["font_path"] == str(
        descriptor.regular_path
    )
    assert context.render_template_reel_settings["bold_font_path"] == str(
        descriptor.bold_path
    )
    assert context.render_template_poster_settings["font_path"] == str(
        descriptor.regular_path
    )
    assert context.render_template_poster_settings["bold_font_path"] == str(
        descriptor.bold_path
    )


def test_ingest_falls_back_to_inter_when_brand_has_no_font_family() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            context = _run_ingest_with_brand_font(
                font_family=None,
                database_url=database.url,
                workspace_dir=workspace_dir,
            )
    descriptor = font_catalog.resolve(None)
    assert descriptor.family == "Inter"
    assert context.render_template_reel_settings["font_path"] == str(
        descriptor.regular_path
    )
    assert context.render_template_reel_settings["bold_font_path"] == str(
        descriptor.bold_path
    )


def test_ingest_falls_back_to_inter_when_brand_has_legacy_unknown_family(
    caplog,
) -> None:
    """Legacy persisted families that left the catalogue do not crash render.

    Feature 28 validates ``font_family`` on PUT, but agencies persisted
    via legacy paths (admin SQL, pre-validator state) may still carry a
    family that the current catalogue does not know. The ingest
    resolver logs a warning and falls back to Inter so the worker
    keeps producing reels.
    """
    import logging

    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            # Use the repository directly to bypass the payload
            # validator and persist a legacy unknown family.
            seeded = seed_tenant(
                database.url, site_id="ckp.ie", workspace_dir=workspace_dir
            )
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                uow.configuration.brand.upsert(
                    agency_id=seeded.agency_id, font_family="Söhne"
                )

            with caplog.at_level(logging.WARNING):
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

    descriptor = font_catalog.resolve(None)
    assert descriptor.family == "Inter"
    assert context.render_template_reel_settings["font_path"] == str(
        descriptor.regular_path
    )
    assert any(
        "Söhne" in record.getMessage() and "catalogue" in record.getMessage()
        for record in caplog.records
    )
