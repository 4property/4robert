from __future__ import annotations

from pathlib import Path
from typing import Protocol

from models.property import Property
from repositories.property_pipeline_repository import DownloadedImage
from application.types import (
    PropertyContext,
    PropertyVideoJob,
    PublishedVideoArtifact,
    RenderedVideoArtifact,
    SelectedPhotoSet,
)


class PropertyInfoService(Protocol):
    def ingest_property(self, job: PropertyVideoJob) -> PropertyContext:
        ...


class PhotoSelectionService(Protocol):
    def select_photos(self, context: PropertyContext) -> SelectedPhotoSet:
        ...


class PhotoSelectionEngine(Protocol):
    def select_photos(
        self,
        *,
        property_item: Property,
        raw_images_root: Path,
        filtered_images_root: Path,
    ) -> tuple[Path, list[DownloadedImage]]:
        ...


class VideoRenderer(Protocol):
    def render_video(
        self,
        context: PropertyContext,
        selected_photos: SelectedPhotoSet,
    ) -> RenderedVideoArtifact:
        ...


class VideoPublisher(Protocol):
    def publish_video(
        self,
        context: PropertyContext,
        rendered_video: RenderedVideoArtifact,
    ) -> PublishedVideoArtifact:
        ...

    def publish_existing_video(
        self,
        context: PropertyContext,
    ) -> PublishedVideoArtifact:
        ...


class JobDispatcher(Protocol):
    def start(self) -> None:
        ...

    def stop(self, timeout: float | None = None) -> None:
        ...

    def enqueue(self, job: PropertyVideoJob) -> None:
        ...

    def wait_for_idle(self, timeout: float = 5.0) -> bool:
        ...

    def is_accepting_jobs(self) -> bool:
        ...


__all__ = [
    "JobDispatcher",
    "PhotoSelectionEngine",
    "PhotoSelectionService",
    "PropertyInfoService",
    "VideoPublisher",
    "VideoRenderer",
]

