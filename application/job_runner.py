from __future__ import annotations

import logging
from pathlib import Path

from application.property_video_pipeline import PropertyVideoPipeline
from application.types import PropertyVideoJob
from core.locking import exclusive_file_lock, property_job_lock_path
from core.logging import LoggedProcess, format_console_block, format_detail_line

logger = logging.getLogger(__name__)


class PropertyVideoJobRunner:
    def __init__(
        self,
        workspace_dir: str | Path,
        *,
        pipeline: PropertyVideoPipeline,
    ) -> None:
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.pipeline = pipeline

    def run(self, job: PropertyVideoJob) -> object | None:
        lock_path = property_job_lock_path(
            self.workspace_dir,
            site_id=job.site_id,
            property_id=job.property_id,
        )
        with LoggedProcess(
            logger,
            "PROPERTY JOB",
            (
                format_detail_line("Event ID", job.event_id, highlight=True),
                format_detail_line("Site ID", job.site_id, highlight=True),
                format_detail_line("Property ID", job.property_id, highlight=True),
                format_detail_line("Lock path", lock_path),
            ),
            total_label="Total time",
        ) as job_process:
            try:
                logger.info(
                    format_console_block(
                        "Property Job Lock Waiting",
                        format_detail_line("Lock path", lock_path),
                    )
                )
                with exclusive_file_lock(lock_path):
                    logger.info(
                        format_console_block(
                            "Property Job Lock Acquired",
                            format_detail_line("Lock path", lock_path, highlight=True),
                        )
                    )
                    published_video = self.pipeline.run_job(job)
            except Exception as exc:
                job_process.fail(
                    exc,
                    format_detail_line("Final status", "FAILED", highlight=True),
                    total_label="Total time",
                )
                raise

            final_status = "noop" if published_video is None else "completed"
            job_process.complete(
                format_detail_line("Final status", final_status.upper(), highlight=True),
                total_label="Total time",
            )
            return published_video


__all__ = ["PropertyVideoJobRunner"]
