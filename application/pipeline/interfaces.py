from __future__ import annotations

from pathlib import Path
from typing import Protocol

from application.pipeline.content_generation import GeneratedPropertyContent
from application.types import (
    PreparedMediaAssets,
    PropertyContext,
    PropertyMediaJob,
    PublishedMediaArtifact,
    RenderedMediaArtifact,
)
from domain.properties.model import Property
from domain.media.types import DownloadedImage


class PropertyInfoService(Protocol):
    def ingest_property(self, job: PropertyMediaJob) -> PropertyContext:
        ...


class ContentGenerator(Protocol):
    def generate_property_content(
        self,
        *,
        property_item: Property,
        property_url: str,
        platforms: tuple[str, ...],
    ) -> GeneratedPropertyContent:
        ...


class MediaPreparationService(Protocol):
    def prepare_assets(self, context: PropertyContext) -> PreparedMediaAssets:
        ...

    def cleanup_prepared_assets(
        self,
        context: PropertyContext,
        prepared_assets: PreparedMediaAssets,
    ) -> None:
        ...


class PhotoSelectionService(MediaPreparationService, Protocol):
    def select_photos(self, context: PropertyContext) -> PreparedMediaAssets:
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


class MediaRenderer(Protocol):
    def render_media(
        self,
        context: PropertyContext,
        prepared_assets: PreparedMediaAssets,
    ) -> RenderedMediaArtifact:
        ...


class MediaPublisher(Protocol):
    def publish_media(
        self,
        context: PropertyContext,
        rendered_media: RenderedMediaArtifact,
    ) -> PublishedMediaArtifact:
        ...

    def publish_existing_media(
        self,
        context: PropertyContext,
    ) -> PublishedMediaArtifact:
        ...


class JobDispatcher(Protocol):
    def start(self) -> None:
        ...

    def stop(self, timeout: float | None = None) -> None:
        ...

    def enqueue(self, job: PropertyMediaJob) -> None:
        ...

    def wait_for_idle(self, timeout: float = 5.0) -> bool:
        ...

    def is_accepting_jobs(self) -> bool:
        ...


__all__ = [
    "ContentGenerator",
    "JobDispatcher",
    "MediaPreparationService",
    "MediaPublisher",
    "MediaRenderer",
    "PhotoSelectionEngine",
    "PhotoSelectionService",
    "PropertyInfoService",
]
