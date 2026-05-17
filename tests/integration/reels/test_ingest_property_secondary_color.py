"""Integration tests for brand-secondary-color injection during ingestion.

Feature 29: ``IngestPropertyIntoReelUseCase`` must resolve the agency's
``BrandSettings.secondary_color`` and stash it onto
``render_template_reel_settings["side_banner_ribbon_background_color"]``
so the downstream renderer (``DefaultMediaRenderer._build_render_data``
+ ``preparation.prepare_reel_render_assets``) drives the side_banner
vertical ribbon with the brand colour instead of the hardcoded
``#FECF4D`` from feature 17. When the agency has no secondary colour
persisted the key is absent and the renderer keeps the historical
fallback.

The poster template does not use the rotated ribbon asset, so the key
is intentionally not propagated to ``render_template_poster_settings``.
"""

from __future__ import annotations

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
    "id": 101,
    "slug": "casa-secundaria",
    "title": {"rendered": "Casa Secundaria"},
    "link": "https://ckp.ie/casa-secundaria",
    "property_status": "for sale",
    "price": "425000",
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
        event_id="event-secondary",
        tenant=tenant,
        property_id=101,
        received_at="2026-05-14T10:00:00+00:00",
        raw_payload_hash="secondary-hash",
        payload=_PAYLOAD,
        publish_context=None,
        job_id="job-secondary",
    )


def _run_ingest_with_brand_secondary(
    *,
    secondary_color: str | None,
    database_url: str,
    workspace_dir,
):
    seeded = seed_tenant(database_url, site_id="ckp.ie", workspace_dir=workspace_dir)
    with DatabaseUnitOfWork(database_url, workspace_dir) as uow:
        assert uow.configuration is not None
        if secondary_color is not None:
            uow.configuration.brand.upsert(
                agency_id=seeded.agency_id, secondary_color=secondary_color
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


def test_ingest_injects_brand_secondary_color_into_reel_settings() -> None:
    """A configured secondary colour rides along inside reel settings."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            context = _run_ingest_with_brand_secondary(
                secondary_color="#FF00FF",
                database_url=database.url,
                workspace_dir=workspace_dir,
            )
    reel_settings = context.render_template_reel_settings
    assert reel_settings is not None
    assert reel_settings.get("side_banner_ribbon_background_color") == "#FF00FF"
    # The poster template must NOT carry the key — the rotated ribbon
    # asset is reel-only.
    poster_settings = context.render_template_poster_settings or {}
    assert "side_banner_ribbon_background_color" not in poster_settings


def test_ingest_omits_secondary_color_when_brand_has_default_white() -> None:
    """A blank / whitespace secondary colour falls back to the hardcoded ribbon.

    ``BrandSettingsRepository.upsert`` seeds new brand rows with
    ``secondary_color="#FFFFFF"`` by default. Even a "default white" is
    still a real colour value persisted in the brand row, so it
    propagates verbatim. Operators who want the historical ribbon
    colour back must either delete the brand row (defensive guard) or
    accept the brand colour — there is no special-case for white.
    """
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            context = _run_ingest_with_brand_secondary(
                secondary_color=None,
                database_url=database.url,
                workspace_dir=workspace_dir,
            )
    reel_settings = context.render_template_reel_settings or {}
    # No brand row was upserted: the resolver returns ``None`` and the
    # renderer keeps the ``#FECF4D`` hardcoded fallback inside
    # ``preparation.prepare_reel_render_assets``.
    assert "side_banner_ribbon_background_color" not in reel_settings
