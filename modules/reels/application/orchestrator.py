"""Reel pipeline orchestrator (worker handler for ``reel_publish``).

Composes the four modern use cases that own a ``reel_publish`` job in
sequence — ingest, prepare, render, persist+publish — letting each use
case open its own short-lived ``DatabaseUnitOfWork``. Replaces the
legacy ``PropertyMediaPipeline`` from
``application/pipeline/media_pipeline.py`` (retired by feature 16)
without changing the job contract: the worker keeps registering
``ReelPipeline.handle`` for the ``reel_publish`` kind.

Three execution paths mirror the legacy orchestrator:

* ``context.is_noop`` → skip prepare/render/publish, return ``None``.
* ``not context.requires_render`` → publish-only retry over the
  existing local artifact.
* otherwise → prepare + render + publish, with a guaranteed cleanup
  of the prepared assets on the way out.

The render step is pure compute + filesystem (no DB). The local
``_LocalArtifactsPublisher`` adapter wires
``PersistLocalArtifactsUseCase`` into the ``local_publisher`` contract
expected by ``PublishReelUseCase`` so the rendered artifact lands on
disk and the workflow transition is committed before the external
publish step proceeds. Each use case owns its own UoW: wrapping the
whole pipeline in a single outer UoW deadlocks against the nested
connection the persist adapter opens for the same row.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from modules.reels.domain.types import PropertyMediaJob, SocialPublishContext
from modules.tenancy.domain.context import TenantContext
from modules.delivery.domain import Job
from modules.reels.application.use_cases.ingest_property_into_reel import (
    IngestPropertyIntoReelUseCase,
)
from modules.reels.application.use_cases.persist_local_artifacts import (
    PersistLocalArtifactsUseCase,
)
from modules.reels.application.use_cases.prepare_reel_assets import (
    PrepareReelAssetsUseCase,
)
from modules.reels.application.use_cases.publish_reel import PublishReelUseCase
from modules.rendering.application.frame_composition import DefaultMediaRenderer
from settings import (
    DATABASE_URL,
    PROPERTY_MEDIA_DELETE_SELECTED_PHOTOS,
    PROPERTY_MEDIA_DELETE_TEMPORARY_FILES,
    SOCIAL_PUBLISHING_ENABLED,
    SOCIAL_PUBLISHING_LOCAL_ONLY,
    SOCIAL_PUBLISHING_PROPERTY_URL_TEMPLATE,
    SOCIAL_PUBLISHING_PROPERTY_URL_TRACKING_PARAMS,
)
from shared.db import DatabaseUnitOfWork
from shared.observability import (
    LoggedProcess,
    format_detail_line,
)

logger = logging.getLogger(__name__)


class ReelPipeline:
    def __init__(
        self,
        *,
        workspace_dir: str | Path,
        database_locator: str | Path | None = None,
    ) -> None:
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.database_locator = (
            DATABASE_URL if database_locator is None else database_locator
        )
        social_publishing_active = (
            SOCIAL_PUBLISHING_ENABLED and not SOCIAL_PUBLISHING_LOCAL_ONLY
        )
        self._ingest = IngestPropertyIntoReelUseCase(
            workspace_dir=self.workspace_dir,
            property_url_template=SOCIAL_PUBLISHING_PROPERTY_URL_TEMPLATE,
            property_url_tracking_params=SOCIAL_PUBLISHING_PROPERTY_URL_TRACKING_PARAMS,
            social_publishing_enabled=social_publishing_active,
            database_locator=self.database_locator,
        )
        self._prepare = PrepareReelAssetsUseCase(
            workspace_dir=self.workspace_dir,
            cleanup_temporary_files=PROPERTY_MEDIA_DELETE_TEMPORARY_FILES,
            cleanup_selected_photos=PROPERTY_MEDIA_DELETE_SELECTED_PHOTOS,
            database_locator=self.database_locator,
        )
        self._renderer = DefaultMediaRenderer(self.workspace_dir)
        self._persist = PersistLocalArtifactsUseCase(
            workspace_dir=self.workspace_dir,
            cleanup_temporary_files=PROPERTY_MEDIA_DELETE_TEMPORARY_FILES,
            database_locator=self.database_locator,
        )
        self._social_publisher: object | None = (
            _build_default_social_property_publisher()
            if social_publishing_active
            else None
        )
        self._publish = PublishReelUseCase(
            local_publisher=_LocalArtifactsPublisher(self._persist),
            workspace_dir=self.workspace_dir,
            social_publisher=self._social_publisher,
            database_locator=self.database_locator,
        )

    def handle(self, job: Job) -> object | None:
        media_job = build_property_media_job(job)
        shared_details = (
            format_detail_line("Event ID", media_job.event_id, highlight=True),
            format_detail_line("Site ID", media_job.site_id, highlight=True),
            format_detail_line("Property ID", media_job.property_id, highlight=True),
        )
        with LoggedProcess(
            logger,
            "PROPERTY MEDIA PIPELINE",
            shared_details,
            total_label="Total time",
        ) as pipeline_process:
            # Each use case opens (and commits) its own short-lived
            # ``DatabaseUnitOfWork``. We deliberately do NOT wrap the
            # whole pipeline in a single outer UoW: the legacy
            # ``_LocalArtifactsPublisher`` adapter the publish step uses
            # opens its own connection internally for the persist write,
            # which would deadlock against an outer connection holding
            # the row lock for the same property. The matching pattern
            # is exercised by ``tests/integration/reels/test_*_flow.py``.
            with LoggedProcess(
                logger, "PROPERTY INGESTION", shared_details
            ) as ingestion_process:
                context = self._ingest.execute(media_job)
                ingestion_process.complete(
                    format_detail_line(
                        "Is noop", "Yes" if context.is_noop else "No"
                    ),
                    format_detail_line(
                        "Requires render",
                        "Yes" if context.requires_render else "No",
                    ),
                    format_detail_line(
                        "Requires external publish",
                        "Yes" if context.requires_external_publish else "No",
                    ),
                )

            if context.is_noop:
                pipeline_process.complete(
                    format_detail_line("Final status", "NOOP", highlight=True),
                    total_label="Total time",
                )
                return None

            if not context.requires_render:
                with LoggedProcess(
                    logger, "EXISTING MEDIA PUBLISH", shared_details
                ) as publish_process:
                    published_media = self._publish.execute_existing(context)
                    publish_process.complete(
                        format_detail_line(
                            "Artifact kind", published_media.artifact_kind
                        ),
                        format_detail_line(
                            "Media path", published_media.media_path
                        ),
                    )
                pipeline_process.complete(
                    format_detail_line(
                        "Final status", "COMPLETED", highlight=True
                    ),
                    format_detail_line("Publish mode", "Existing local media"),
                    total_label="Total time",
                )
                return published_media

            prepared_assets = self._prepare.execute(context)
            try:
                with LoggedProcess(
                    logger, "MEDIA RENDER", shared_details
                ) as render_process:
                    rendered_media = self._renderer.render_media(
                        context, prepared_assets
                    )
                    render_process.complete(
                        format_detail_line(
                            "Artifact kind", rendered_media.artifact_kind
                        ),
                        format_detail_line(
                            "Media path", rendered_media.media_path
                        ),
                    )
                with LoggedProcess(
                    logger, "MEDIA PUBLISH", shared_details
                ) as publish_process:
                    published_media = self._publish.execute(
                        context, rendered_media
                    )
                    publish_process.complete(
                        format_detail_line(
                            "Artifact kind", published_media.artifact_kind
                        ),
                        format_detail_line(
                            "Media path", published_media.media_path
                        ),
                    )
            finally:
                self._prepare.cleanup(context, prepared_assets)

            pipeline_process.complete(
                format_detail_line("Final status", "COMPLETED", highlight=True),
                format_detail_line("Artifact kind", published_media.artifact_kind),
                format_detail_line("Media path", published_media.media_path),
                total_label="Total time",
            )
            return published_media


class _LocalArtifactsPublisher:
    """Inline adapter binding ``PersistLocalArtifactsUseCase`` to the
    ``local_publisher`` contract expected by ``PublishReelUseCase``.

    Equivalent to the ``FileSystemMediaPublisher`` adapter that lived in
    ``application/bootstrap/pipeline_adapters.py`` (retired by feature
    16). The persist call opens its own short-lived
    ``DatabaseUnitOfWork`` (built from ``database_locator``) so the
    revision row, workflow transition and outbox event commit before
    ``_publish_externally`` stamps the publish status.
    """

    def __init__(self, persist: PersistLocalArtifactsUseCase) -> None:
        self._persist = persist

    def publish_media(self, context, rendered_media):
        return self._persist.execute(context, rendered_media)

    def publish_existing_media(self, context):
        return self._persist.execute_existing(context)


def _build_default_social_property_publisher():
    from modules.publishing.infrastructure.adapters.gohighlevel.factory import (
        build_default_social_property_publisher,
    )

    return build_default_social_property_publisher()


def build_property_media_job(job: Job) -> PropertyMediaJob:
    publish_context_payload = _mapping_to_dict(job.publish_context)
    if job.provider_secret_bundle:
        publish_context_payload["access_token"] = job.provider_secret_bundle

    return PropertyMediaJob(
        event_id=job.event_id,
        tenant=TenantContext(
            site_id=job.external_source_id,
            agency_id=job.agency_id,
            wordpress_source_id=job.ingestion_source_id,
        ),
        property_id=job.property_id,
        received_at=job.received_at,
        raw_payload_hash=job.raw_payload_hash,
        payload=_mapping_to_dict(job.payload),
        publish_context=SocialPublishContext.from_dict(publish_context_payload),
        job_id=job.job_id,
    )


def _mapping_to_dict(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): item for key, item in dict(value).items()}


__all__ = ["ReelPipeline", "build_property_media_job"]
