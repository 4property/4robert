"""Integration tests for brand-primary-color → side_banner panel injection.

Hotfix 2026-05-15: ``IngestPropertyIntoReelUseCase`` must resolve the
agency's ``BrandSettings.primary_color`` and stash it onto
``render_template_reel_settings["side_banner_panel_color"]`` AND
``render_template_poster_settings["side_banner_panel_color"]`` so the
side_banner header / footer panels render with the brand colour. The
cascade for the panel fill is:

    BrandSettings.primary_color
      → property.wppd_accent_background_color (per-property webhook colour)
      → ``black@0.38`` / ``black@0.46`` hardcoded inside
        ``build_overlay_filter``.

When the agency has no brand row persisted, the key is absent and the
renderer falls back to the existing ``accent_background_color`` resolution
(``fallback_accent_*`` keys from feature 16 take over).
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
    "id": 202,
    "slug": "casa-panel-color",
    "title": {"rendered": "Casa Panel Color"},
    "link": "https://ckp.ie/casa-panel-color",
    "property_status": "for sale",
    "price": "525000",
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
        event_id="event-panel",
        tenant=tenant,
        property_id=202,
        received_at="2026-05-15T10:00:00+00:00",
        raw_payload_hash="panel-hash",
        payload=_PAYLOAD,
        publish_context=None,
        job_id="job-panel",
    )


def _run_ingest_with_brand_primary(
    *,
    primary_color: str | None,
    database_url: str,
    workspace_dir,
):
    seeded = seed_tenant(database_url, site_id="ckp.ie", workspace_dir=workspace_dir)
    with DatabaseUnitOfWork(database_url, workspace_dir) as uow:
        assert uow.configuration is not None
        if primary_color is not None:
            uow.configuration.brand.upsert(
                agency_id=seeded.agency_id, primary_color=primary_color
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


def test_ingest_injects_brand_primary_color_into_reel_and_poster_settings() -> None:
    """A configured primary colour rides along inside BOTH reel and poster settings.

    The side_banner header / footer is rendered in both the segmented
    reel (``render_reel.py``) and the cover poster (``poster.py``), so
    the ingest must stash the brand colour on both renderer settings
    dicts for the cascade to fire in both paths.
    """
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            context = _run_ingest_with_brand_primary(
                primary_color="#FF0000",
                database_url=database.url,
                workspace_dir=workspace_dir,
            )
    reel_settings = context.render_template_reel_settings or {}
    poster_settings = context.render_template_poster_settings or {}
    assert reel_settings.get("side_banner_panel_color") == "#FF0000"
    assert poster_settings.get("side_banner_panel_color") == "#FF0000"


def test_ingest_omits_panel_color_when_brand_row_absent() -> None:
    """Without a brand row, the key is not injected — renderer falls back to webhook accent.

    ``_resolve_brand_primary_color`` returns ``None`` when there is no
    persisted brand for the agency; the helper skips the ``setdefault``
    so the renderer's ``side_banner_panel_color`` field stays ``None``
    and the cascade drops to ``accent_background_color`` (which itself
    may come from ``fallback_accent_background_color`` if the webhook
    omits its own ``wppd_accent_background_color``).
    """
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            context = _run_ingest_with_brand_primary(
                primary_color=None,
                database_url=database.url,
                workspace_dir=workspace_dir,
            )
    reel_settings = context.render_template_reel_settings or {}
    poster_settings = context.render_template_poster_settings or {}
    assert "side_banner_panel_color" not in reel_settings
    assert "side_banner_panel_color" not in poster_settings
