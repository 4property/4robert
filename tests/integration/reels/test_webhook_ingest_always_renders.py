"""Integration guard for the 2026-05-19 "always render" ingest policy.

Background
----------
Before this change, when a webhook ingest arrived with the same content
fingerprint as the previously persisted ``reels`` row and the local
artefacts were still present on disk, the use case returned
``requires_render=False`` / ``is_noop=True``. The orchestrator would
then take the ``EXISTING MEDIA PUBLISH`` fast path and re-use the old
MP4 verbatim.

That short-circuit ignored brand / subtitle overrides
(``font_family``, accent colors, subtitle copy) because they were
deliberately NOT included in ``content_snapshot`` — so changing a font
on the brand settings never moved the fingerprint and stale renders
leaked into publish.

This test pins the new contract: re-ingesting the **same** property
payload twice in a row against Postgres must produce
``requires_render=True`` on both runs. The fast-path is dead for the
ingest flow.
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
    "id": 99,
    "slug": "always-render",
    "title": {"rendered": "Always Render"},
    "link": "https://ckp.ie/always-render",
    "property_status": "for sale",
    "price": "300000",
    "wppd_pics": ["https://ckp.ie/img1.jpg"],
}


def _build_job(
    *,
    event_id: str,
    job_id: str,
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
        event_id=event_id,
        tenant=tenant,
        property_id=int(_PAYLOAD["id"]),  # type: ignore[arg-type]
        received_at="2026-05-19T10:00:00+00:00",
        raw_payload_hash="hash-always-render",
        payload=_PAYLOAD,
        publish_context=None,
        job_id=job_id,
    )


def test_webhook_ingest_always_requires_render() -> None:
    """Two consecutive webhook ingests of the same payload both render.

    First run is a cold ingest with no prior ``reels`` row — obviously
    ``requires_render`` should be ``True``. Second run replays the exact
    same payload after the row has been persisted (matching
    fingerprint, matching snapshot). Under the legacy policy the second
    call would have returned ``requires_render=False`` and ``is_noop=True``
    (via the ``EXISTING MEDIA PUBLISH`` fast-path in the orchestrator).
    The new policy must keep ``requires_render=True`` so every webhook
    triggers a fresh render.
    """

    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url, site_id="ckp.ie", workspace_dir=workspace_dir
            )
            use_case = IngestPropertyIntoReelUseCase(
                workspace_dir=workspace_dir,
                property_url_template="",
                property_url_tracking_params=None,
                social_publishing_enabled=False,
                database_locator=database.url,
            )

            # ----- First ingest (cold) -----
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                first = use_case.execute(
                    _build_job(
                        event_id="event-1",
                        job_id="job-1",
                        agency_id=seeded.agency_id,
                        ingestion_source_id=seeded.ingestion_source_id,
                        site_id=seeded.external_source_id,
                    ),
                    uow=uow,
                )

            assert first.requires_render is True
            assert first.is_noop is False

            # ----- Second ingest (same payload) -----
            # The ``reels`` row now exists with the matching
            # ``content_fingerprint`` / ``content_snapshot``. The legacy
            # fast-path would have returned ``requires_render=False``
            # here. The new policy forces a fresh render every time.
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                second = use_case.execute(
                    _build_job(
                        event_id="event-2",
                        job_id="job-2",
                        agency_id=seeded.agency_id,
                        ingestion_source_id=seeded.ingestion_source_id,
                        site_id=seeded.external_source_id,
                    ),
                    uow=uow,
                )

            # Sanity: the fingerprint *did* stay stable (same payload),
            # so the legacy "content_changed" signal is False — yet the
            # new policy still requires a render.
            assert second.content_fingerprint == first.content_fingerprint
            assert second.requires_render is True
            assert second.is_noop is False
