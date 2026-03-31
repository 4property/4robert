from __future__ import annotations

import logging

from application.interfaces import (
    MediaPreparationService,
    MediaPublisher,
    MediaRenderer,
    PropertyInfoService,
)
from application.types import PropertyMediaJob, PublishedMediaArtifact
from core.logging import LoggedProcess, format_detail_line

logger = logging.getLogger(__name__)


class PropertyMediaPipeline:
    def __init__(
        self,
        *,
        property_info_service: PropertyInfoService,
        media_preparation_service: MediaPreparationService,
        media_renderer: MediaRenderer,
        media_publisher: MediaPublisher,
    ) -> None:
        self.property_info_service = property_info_service
        self.media_preparation_service = media_preparation_service
        self.media_renderer = media_renderer
        self.media_publisher = media_publisher

    def run_job(self, job: PropertyMediaJob) -> PublishedMediaArtifact | None:
        shared_details = (
            format_detail_line("Event ID", job.event_id, highlight=True),
            format_detail_line("Site ID", job.site_id, highlight=True),
            format_detail_line("Property ID", job.property_id, highlight=True),
        )
        with LoggedProcess(
            logger,
            "PROPERTY MEDIA PIPELINE",
            shared_details,
            total_label="Total time",
        ) as pipeline_process:
            with LoggedProcess(logger, "PROPERTY INGESTION", shared_details) as ingestion_process:
                context = self.property_info_service.ingest_property(job)
                ingestion_process.complete(
                    format_detail_line("Is noop", "Yes" if context.is_noop else "No"),
                    format_detail_line(
                        "Asset strategy",
                        context.delivery_plan.asset_strategy,
                    ),
                    format_detail_line(
                        "Artifact kind",
                        context.delivery_plan.artifact_kind,
                    ),
                    format_detail_line(
                        "Requires asset preparation",
                        "Yes" if context.requires_asset_preparation else "No",
                    ),
                    format_detail_line("Requires render", "Yes" if context.requires_render else "No"),
                    format_detail_line("Requires external publish", "Yes" if context.requires_external_publish else "No"),
                )

            if context.is_noop:
                pipeline_process.complete(
                    format_detail_line("Final status", "NOOP", highlight=True),
                    format_detail_line("Summary", "The property did not require a new render or publish."),
                    total_label="Total time",
                )
                return None

            if not context.requires_render:
                with LoggedProcess(logger, "EXISTING MEDIA PUBLISH", shared_details) as publish_process:
                    published_media = self.media_publisher.publish_existing_media(context)
                    publish_process.complete(
                        format_detail_line("Artifact kind", published_media.artifact_kind),
                        format_detail_line("Media path", published_media.media_path),
                        format_detail_line("Metadata path", published_media.metadata_path or "<none>"),
                    )
                pipeline_process.complete(
                    format_detail_line("Final status", "COMPLETED", highlight=True),
                    format_detail_line("Publish mode", "Existing local media"),
                    total_label="Total time",
                )
                return published_media

            with LoggedProcess(logger, "MEDIA PREPARATION", shared_details) as preparation_process:
                prepared_assets = self.media_preparation_service.prepare_assets(context)
                preparation_process.complete(
                    format_detail_line("Prepared image count", len(prepared_assets.selected_photo_paths), highlight=True),
                    format_detail_line("Prepared directory", prepared_assets.selected_dir),
                    format_detail_line("Primary image", prepared_assets.primary_image_path or "<none>"),
                )

            with LoggedProcess(logger, "MEDIA RENDER", shared_details) as render_process:
                rendered_media = self.media_renderer.render_media(context, prepared_assets)
                render_process.complete(
                    format_detail_line("Artifact kind", rendered_media.artifact_kind),
                    format_detail_line("Media path", rendered_media.media_path),
                    format_detail_line("Metadata path", rendered_media.metadata_path or "<none>"),
                )

            with LoggedProcess(logger, "MEDIA PUBLISH", shared_details) as publish_process:
                published_media = self.media_publisher.publish_media(context, rendered_media)
                publish_process.complete(
                    format_detail_line("Artifact kind", published_media.artifact_kind),
                    format_detail_line("Media path", published_media.media_path),
                    format_detail_line("Metadata path", published_media.metadata_path or "<none>"),
                )

            pipeline_process.complete(
                format_detail_line("Final status", "COMPLETED", highlight=True),
                format_detail_line("Artifact kind", published_media.artifact_kind),
                format_detail_line("Media path", published_media.media_path),
                format_detail_line("Metadata path", published_media.metadata_path or "<none>"),
                total_label="Total time",
            )
            return published_media


PropertyVideoPipeline = PropertyMediaPipeline


__all__ = ["PropertyMediaPipeline", "PropertyVideoPipeline"]
