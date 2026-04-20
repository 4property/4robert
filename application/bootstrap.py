from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from application.content_generation import DeterministicPropertyContentGenerator
from application.default_services import (
    CompositeMediaPublisher,
    DefaultMediaPreparationService,
    DefaultPropertyInfoService,
    DefaultMediaRenderer,
    FileSystemMediaPublisher,
)
from application.dispatching import SqliteJobDispatcher
from application.job_runner import PropertyMediaJobRunner
from application.property_video_pipeline import PropertyMediaPipeline, PropertyVideoPipeline
from application.types import PropertyMediaJob, PropertyVideoJob
from repositories.sqlite_work_unit import SqliteWorkUnit
from config import (
    DATABASE_FILENAME,
    DATABASE_URL,
    GO_HIGH_LEVEL_API_VERSION,
    GO_HIGH_LEVEL_BASE_URL,
    OUTBOUND_HTTP_TIMEOUT_SECONDS,
    PROPERTY_MEDIA_DELETE_SELECTED_PHOTOS,
    PROPERTY_MEDIA_DELETE_TEMPORARY_FILES,
    SOCIAL_PUBLISHING_ENABLED,
    SOCIAL_PUBLISHING_LOCAL_ONLY,
    SOCIAL_PUBLISHING_POST_STATUS_POLL_ATTEMPTS,
    SOCIAL_PUBLISHING_POST_STATUS_POLL_INTERVAL_SECONDS,
    SOCIAL_PUBLISHING_RETRY_ATTEMPTS,
    SOCIAL_PUBLISHING_RETRY_BACKOFF_SECONDS,
    SOCIAL_PUBLISHING_PROPERTY_URL_TEMPLATE,
    SOCIAL_PUBLISHING_PROPERTY_URL_TRACKING_PARAMS,
    WEBHOOK_JOB_MAX_ATTEMPTS,
    WEBHOOK_JOB_RETRY_BACKOFF_SECONDS,
    WEBHOOK_QUEUE_LEASE_SECONDS,
    WEBHOOK_QUEUE_POLL_INTERVAL_SECONDS,
    WEBHOOK_SHUTDOWN_TIMEOUT_SECONDS,
    WEBHOOK_WORKER_COUNT,
)
from services.social_delivery import (
    GoHighLevelClient,
    GoHighLevelMediaService,
    GoHighLevelPropertyPublisher,
    GoHighLevelPublisher,
    GoHighLevelSocialService,
    select_first_available_location_user,
)


def build_default_social_property_publisher() -> GoHighLevelPropertyPublisher:
    client = GoHighLevelClient(
        base_url=GO_HIGH_LEVEL_BASE_URL,
        api_version=GO_HIGH_LEVEL_API_VERSION,
        timeout_seconds=OUTBOUND_HTTP_TIMEOUT_SECONDS,
    )
    publisher = GoHighLevelPublisher(
        media_service=GoHighLevelMediaService(client=client),
        social_service=GoHighLevelSocialService(client=client),
        fallback_user_selector=select_first_available_location_user,
        retry_attempts=SOCIAL_PUBLISHING_RETRY_ATTEMPTS,
        retry_backoff_seconds=SOCIAL_PUBLISHING_RETRY_BACKOFF_SECONDS,
        post_status_poll_attempts=SOCIAL_PUBLISHING_POST_STATUS_POLL_ATTEMPTS,
        post_status_poll_interval_seconds=SOCIAL_PUBLISHING_POST_STATUS_POLL_INTERVAL_SECONDS,
    )
    return GoHighLevelPropertyPublisher(
        publisher=publisher,
    )


def build_default_unit_of_work_factory(workspace_dir: str | Path):
    workspace_path = Path(workspace_dir).expanduser().resolve()
    return lambda: SqliteWorkUnit(workspace_path / DATABASE_FILENAME, workspace_path)


def build_runtime_unit_of_work_factory(
    workspace_dir: str | Path,
    *,
    database_locator: str | Path | None = None,
):
    workspace_path = Path(workspace_dir).expanduser().resolve()
    resolved_database_locator = DATABASE_URL if database_locator is None else database_locator
    return lambda: SqliteWorkUnit(resolved_database_locator, workspace_path)


def build_default_property_media_pipeline(
    workspace_dir: str | Path,
    *,
    database_locator: str | Path | None = None,
) -> PropertyMediaPipeline:
    workspace_path = Path(workspace_dir).expanduser().resolve()
    unit_of_work_factory = build_runtime_unit_of_work_factory(
        workspace_path,
        database_locator=database_locator,
    )
    social_publishing_active = SOCIAL_PUBLISHING_ENABLED and not SOCIAL_PUBLISHING_LOCAL_ONLY
    social_property_publisher = (
        build_default_social_property_publisher()
        if social_publishing_active
        else None
    )
    return PropertyMediaPipeline(
        property_info_service=DefaultPropertyInfoService(
            workspace_path,
            unit_of_work_factory=unit_of_work_factory,
            property_url_template=SOCIAL_PUBLISHING_PROPERTY_URL_TEMPLATE,
            property_url_tracking_params=SOCIAL_PUBLISHING_PROPERTY_URL_TRACKING_PARAMS,
            social_publishing_enabled=social_publishing_active,
            content_generator=DeterministicPropertyContentGenerator(),
        ),
        media_preparation_service=DefaultMediaPreparationService(
            workspace_path,
            unit_of_work_factory=unit_of_work_factory,
            cleanup_temporary_files=PROPERTY_MEDIA_DELETE_TEMPORARY_FILES,
            cleanup_selected_photos=PROPERTY_MEDIA_DELETE_SELECTED_PHOTOS,
        ),
        media_renderer=DefaultMediaRenderer(workspace_path),
        media_publisher=CompositeMediaPublisher(
            local_publisher=FileSystemMediaPublisher(
                unit_of_work_factory=unit_of_work_factory,
                cleanup_temporary_files=PROPERTY_MEDIA_DELETE_TEMPORARY_FILES,
            ),
            unit_of_work_factory=unit_of_work_factory,
            social_publisher=social_property_publisher,
        ),
    )


def build_default_property_video_pipeline(
    workspace_dir: str | Path,
    *,
    database_locator: str | Path | None = None,
) -> PropertyVideoPipeline:
    return build_default_property_media_pipeline(
        workspace_dir,
        database_locator=database_locator,
    )


def build_default_job_handler(
    workspace_dir: str | Path,
    *,
    database_locator: str | Path | None = None,
    pipeline: PropertyMediaPipeline | PropertyVideoPipeline | None = None,
) -> Callable[[PropertyVideoJob], object | None]:
    workspace_path = Path(workspace_dir).expanduser().resolve()
    active_pipeline = pipeline or build_default_property_media_pipeline(
        workspace_dir,
        database_locator=database_locator,
    )
    runner = PropertyMediaJobRunner(
        workspace_path,
        pipeline=active_pipeline,
    )

    def handle_job(job: PropertyMediaJob) -> object | None:
        return runner.run(job)

    return handle_job


def build_default_job_dispatcher(
    workspace_dir: str | Path,
    *,
    database_locator: str | Path | None = None,
    worker_count: int = WEBHOOK_WORKER_COUNT,
    pipeline: PropertyMediaPipeline | PropertyVideoPipeline | None = None,
) -> SqliteJobDispatcher:
    return SqliteJobDispatcher(
        handler=build_default_job_handler(
            workspace_dir,
            database_locator=database_locator,
            pipeline=pipeline,
        ),
        unit_of_work_factory=build_runtime_unit_of_work_factory(
            workspace_dir,
            database_locator=database_locator,
        ),
        worker_count=worker_count,
        poll_interval_seconds=WEBHOOK_QUEUE_POLL_INTERVAL_SECONDS,
        lease_seconds=WEBHOOK_QUEUE_LEASE_SECONDS,
        retry_backoff_seconds=WEBHOOK_JOB_RETRY_BACKOFF_SECONDS,
        job_max_attempts=WEBHOOK_JOB_MAX_ATTEMPTS,
    )


__all__ = [
    "WEBHOOK_SHUTDOWN_TIMEOUT_SECONDS",
    "build_default_job_dispatcher",
    "build_default_job_handler",
    "build_default_property_media_pipeline",
    "build_default_property_video_pipeline",
    "build_runtime_unit_of_work_factory",
    "build_default_social_property_publisher",
    "build_default_unit_of_work_factory",
]

