from __future__ import annotations

import logging

from application.interfaces import PhotoSelectionService, PropertyInfoService, VideoPublisher, VideoRenderer
from application.types import PropertyVideoJob, PublishedVideoArtifact
from core.logging import LoggedProcess, format_detail_line

logger = logging.getLogger(__name__)


class PropertyVideoPipeline:
    def __init__(
        self,
        *,
        property_info_service: PropertyInfoService,
        photo_selection_service: PhotoSelectionService,
        video_renderer: VideoRenderer,
        video_publisher: VideoPublisher,
    ) -> None:
        self.property_info_service = property_info_service
        self.photo_selection_service = photo_selection_service
        self.video_renderer = video_renderer
        self.video_publisher = video_publisher

    def run_job(self, job: PropertyVideoJob) -> PublishedVideoArtifact | None:
        shared_details = (
            format_detail_line("Event ID", job.event_id, highlight=True),
            format_detail_line("Site ID", job.site_id, highlight=True),
            format_detail_line("Property ID", job.property_id, highlight=True),
        )
        with LoggedProcess(
            logger,
            "PROPERTY PIPELINE",
            shared_details,
            total_label="Total time",
        ) as pipeline_process:
            with LoggedProcess(logger, "PROPERTY INGESTION", shared_details) as ingestion_process:
                context = self.property_info_service.ingest_property(job)
                ingestion_process.complete(
                    format_detail_line("Is noop", "Yes" if context.is_noop else "No"),
                    format_detail_line("Requires photo selection", "Yes" if context.requires_photo_selection else "No"),
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
                with LoggedProcess(logger, "EXISTING VIDEO PUBLISH", shared_details) as publish_process:
                    published_video = self.video_publisher.publish_existing_video(context)
                    publish_process.complete(
                        format_detail_line("Manifest path", published_video.manifest_path),
                        format_detail_line("Video path", published_video.video_path),
                    )
                pipeline_process.complete(
                    format_detail_line("Final status", "COMPLETED", highlight=True),
                    format_detail_line("Publish mode", "Existing local video"),
                    total_label="Total time",
                )
                return published_video

            with LoggedProcess(logger, "PHOTO SELECTION", shared_details) as selection_process:
                selected_photos = self.photo_selection_service.select_photos(context)
                selection_process.complete(
                    format_detail_line("Selected photo count", len(selected_photos.selected_photo_paths), highlight=True),
                    format_detail_line("Selected directory", selected_photos.selected_dir),
                )

            with LoggedProcess(logger, "VIDEO RENDER", shared_details) as render_process:
                rendered_video = self.video_renderer.render_video(context, selected_photos)
                render_process.complete(
                    format_detail_line("Manifest path", rendered_video.manifest_path),
                    format_detail_line("Video path", rendered_video.video_path),
                )

            with LoggedProcess(logger, "VIDEO PUBLISH", shared_details) as publish_process:
                published_video = self.video_publisher.publish_video(context, rendered_video)
                publish_process.complete(
                    format_detail_line("Manifest path", published_video.manifest_path),
                    format_detail_line("Video path", published_video.video_path),
                )

            pipeline_process.complete(
                format_detail_line("Final status", "COMPLETED", highlight=True),
                format_detail_line("Manifest path", published_video.manifest_path),
                format_detail_line("Video path", published_video.video_path),
                total_label="Total time",
            )
            return published_video


__all__ = ["PropertyVideoPipeline"]
