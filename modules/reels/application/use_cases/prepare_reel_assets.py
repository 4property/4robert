"""Prepare media assets for the reels pipeline (step 2).

This is step 2 of the property media pipeline (was the body of
`DefaultMediaPreparationService.prepare_assets` in
`application/pipeline/media_services.py`).

Responsibilities:
  - resolve the on-disk selected directory layout for a property;
  - either reuse already-prepared assets, run the curated AI photo selection,
    or download a single primary image (status reels);
  - persist `properties.image_folder` and `property_images` rows via the
    modern catalog repos and bump `reels.workflow_state` to `assets_prepared`;
  - return a `PreparedMediaAssets` value the legacy steps 3/4 (still living
    in `application/pipeline/media_services.py`) can consume.

Bridge note (Phase 2): the legacy `DefaultMediaPreparationService` adapter in
`application/pipeline/media_services.py` accepts the historic
`unit_of_work_factory` to keep the bootstrap signature stable, but that
factory is **not** consulted from this use case — the use case opens its own
modern `DatabaseUnitOfWork`. Feature 14 will collapse the bridge once steps
3/4 also migrate.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from modules.catalog.domain.wordpress_property import Property
from modules.reels.domain.types import PreparedMediaAssets, PropertyContext
from shared.errors import PhotoFilteringError
from shared.media_cleanup import (
    DEFAULT_DELETE_SELECTED_PHOTOS,
    DEFAULT_DELETE_TEMPORARY_FILES,
    should_cleanup_raw_property_dir,
    should_cleanup_selected_assets,
)
from shared.observability import build_log_context, format_console_block, format_detail_line
from modules.rendering.infrastructure.photos import download_and_filter_property_images
from modules.rendering.infrastructure.photos.downloads import download_image
from modules.rendering.infrastructure.photos.filesystem import (
    list_image_files,
    prepare_property_directories,
)
from modules.rendering.infrastructure.photos.naming import (
    PRIMARY_IMAGE_STEM,
    build_primary_image_filename,
)
from settings import DEFAULT_PHOTOS_TO_SELECT, SELECTED_PHOTOS_DIRNAME
from shared.db import DatabaseUnitOfWork

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _build_property_record(
    property_item: Property,
    *,
    agency_id: str,
    ingestion_source_id: str,
    external_source_id: str,
    fetched_at: str,
) -> dict[str, Any]:
    """Mirror of the catalog upsert payload used by the ingest use case.

    Translates the legacy column names (`site_id`, `wordpress_source_id`)
    onto the modern ones (`external_source_id`, `ingestion_source_id`) and
    drops legacy-only columns the modern schema does not expose. Duplicated
    here (rather than imported from `ingest_property_into_reel`) to keep the
    use cases independently testable: each one owns its property record
    payload and can evolve without coupling the other.
    """

    record = property_item.to_db_record(image_folder="", fetched_at=fetched_at)
    record["agency_id"] = agency_id
    record["ingestion_source_id"] = ingestion_source_id
    record["external_source_id"] = external_source_id
    for legacy_column in ("image_folder", "social_publish_status", "social_publish_details_json"):
        record.pop(legacy_column, None)
    return record


class LocalPhotoSelectionEngine:
    """Thin wrapper around `download_and_filter_property_images` (legacy).

    Kept as a class (rather than a free function) so unit tests can swap an
    instance into the use case via the `engine=` constructor argument, and
    so the legacy adapter can re-export it from `media_services.py` for the
    bootstrap path.
    """

    def __init__(
        self,
        *,
        photos_to_select: int = DEFAULT_PHOTOS_TO_SELECT,
        cleanup_temporary_files: bool = DEFAULT_DELETE_TEMPORARY_FILES,
    ) -> None:
        self.photos_to_select = photos_to_select
        self.cleanup_temporary_files = bool(cleanup_temporary_files)

    def select_photos(
        self,
        *,
        property_item: Property,
        raw_images_root: Path,
        filtered_images_root: Path,
    ) -> tuple[Path, list[tuple[int, str, Path | None]]]:
        return download_and_filter_property_images(
            property_item,
            raw_images_root,
            filtered_images_root,
            photos_to_select=self.photos_to_select,
            cleanup_temporary_files=self.cleanup_temporary_files,
        )


class PrepareReelAssetsUseCase:
    """Step 2 of the reel pipeline: prepare media assets for the property."""

    def __init__(
        self,
        workspace_dir: str | Path,
        *,
        engine: LocalPhotoSelectionEngine | None = None,
        cleanup_temporary_files: bool = DEFAULT_DELETE_TEMPORARY_FILES,
        cleanup_selected_photos: bool = DEFAULT_DELETE_SELECTED_PHOTOS,
        database_locator: str | Path | None = None,
    ) -> None:
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.cleanup_temporary_files = bool(cleanup_temporary_files)
        self.cleanup_selected_photos = bool(cleanup_selected_photos)
        self.engine = engine or LocalPhotoSelectionEngine(
            cleanup_temporary_files=self.cleanup_temporary_files,
        )
        if database_locator is None:
            from settings import DATABASE_URL

            database_locator = DATABASE_URL
        self.database_locator = database_locator

    def execute(
        self,
        context: PropertyContext,
        *,
        uow: DatabaseUnitOfWork | None = None,
    ) -> PreparedMediaAssets:
        if not context.requires_asset_preparation:
            existing_assets = self._load_existing_assets(context)
            if (
                existing_assets.selected_photo_paths
                or existing_assets.primary_image_path is not None
            ):
                return existing_assets

        if uow is None:
            with DatabaseUnitOfWork(
                self.database_locator, base_dir=self.workspace_dir
            ) as managed_uow:
                return self._prepare_with_uow(context, uow=managed_uow)
        return self._prepare_with_uow(context, uow=uow)

    def cleanup(
        self,
        context: PropertyContext,
        prepared_assets: PreparedMediaAssets,
    ) -> None:
        if not should_cleanup_selected_assets(self.cleanup_selected_photos):
            return
        if not prepared_assets.selected_dir.exists():
            return
        shutil.rmtree(prepared_assets.selected_dir, ignore_errors=True)
        logger.info(
            format_console_block(
                "Prepared Media Assets Cleaned",
                format_detail_line("Site ID", context.site_id),
                format_detail_line("Property ID", context.property.id),
                format_detail_line(
                    "Delete selected photos",
                    "yes" if self.cleanup_selected_photos else "no",
                ),
                format_detail_line("Selected directory", prepared_assets.selected_dir),
            )
        )

    # ------------------------------------------------------------------
    # public static helpers (consumed by the ingest use case)
    # ------------------------------------------------------------------

    @staticmethod
    def resolve_selected_dir(
        *,
        storage_paths,
        property_item: Property,
        state: Any | None = None,
    ) -> Path:
        """Return the on-disk directory that hosts the curated photos.

        `state` may be a modern `ReelState` or any object exposing
        `selected_image_folder`; the legacy `PropertyPipelineState` worked
        the same way. Passing `None` falls back to the canonical layout.
        """

        selected_image_folder = ""
        if state is not None:
            selected_image_folder = getattr(state, "selected_image_folder", "") or ""
        if selected_image_folder:
            return (storage_paths.workspace_dir / selected_image_folder).resolve()
        return (
            storage_paths.filtered_images_root
            / property_item.folder_name
            / SELECTED_PHOTOS_DIRNAME
        ).resolve()

    @staticmethod
    def resolve_primary_image_from_dir(selected_dir: Path) -> Path | None:
        if not selected_dir.exists():
            return None
        image_paths = tuple(list_image_files(selected_dir))
        for image_path in image_paths:
            if image_path.stem.lower() == PRIMARY_IMAGE_STEM:
                return image_path
        return image_paths[0] if image_paths else None

    # ------------------------------------------------------------------
    # internal orchestration
    # ------------------------------------------------------------------

    def _prepare_with_uow(
        self,
        context: PropertyContext,
        *,
        uow: DatabaseUnitOfWork,
    ) -> PreparedMediaAssets:
        if uow.catalog is None or uow.reels is None:
            raise RuntimeError("The unit of work is not active.")
        if context.delivery_plan.uses_primary_image_only:
            return self._prepare_primary_only_assets(context, uow=uow)
        return self._prepare_curated_assets(context, uow=uow)

    def _load_existing_assets(self, context: PropertyContext) -> PreparedMediaAssets:
        selected_dir = self.resolve_selected_dir(
            storage_paths=context.storage_paths,
            property_item=context.property,
        )
        selected_photo_paths = (
            tuple(list_image_files(selected_dir)) if selected_dir.exists() else ()
        )
        return PreparedMediaAssets(
            selected_dir=selected_dir,
            selected_photo_paths=selected_photo_paths,
            downloaded_images=(),
            primary_image_path=self.resolve_primary_image_from_dir(selected_dir),
        )

    def _prepare_curated_assets(
        self,
        context: PropertyContext,
        *,
        uow: DatabaseUnitOfWork,
    ) -> PreparedMediaAssets:
        try:
            selected_dir, downloaded_images = self.engine.select_photos(
                property_item=context.property,
                raw_images_root=context.storage_paths.raw_images_root,
                filtered_images_root=context.storage_paths.filtered_images_root,
            )
        except PhotoFilteringError:
            raise
        except Exception as exc:
            raise PhotoFilteringError(
                f"Failed to prepare curated property images for property {context.property.id}.",
                code="CURATED_ASSET_PREPARATION_FAILED",
                context=build_log_context(
                    site_id=context.site_id,
                    property_id=context.property.id,
                    asset_strategy=context.delivery_plan.asset_strategy,
                ),
                cause=exc,
            ) from exc

        self._persist_assets(
            context=context,
            selected_dir=selected_dir,
            downloaded_images=downloaded_images,
            uow=uow,
        )

        selected_photo_paths = (
            tuple(list_image_files(selected_dir)) if selected_dir.exists() else ()
        )
        primary_image_path = self.resolve_primary_image_from_dir(selected_dir)
        if not selected_photo_paths and primary_image_path is None:
            raise PhotoFilteringError(
                f"No curated images were prepared for property {context.property.id}.",
                code="CURATED_ASSET_SET_EMPTY",
                context=build_log_context(
                    site_id=context.site_id,
                    property_id=context.property.id,
                    selected_dir=selected_dir,
                ),
            )

        logger.info(
            format_console_block(
                "Curated Media Assets Prepared",
                format_detail_line("Site ID", context.site_id),
                format_detail_line("Property ID", context.property.id),
                format_detail_line("Selected image count", len(selected_photo_paths)),
                format_detail_line("Selected directory", selected_dir),
                format_detail_line("Primary image", primary_image_path or "<none>"),
            )
        )
        return PreparedMediaAssets(
            selected_dir=selected_dir,
            selected_photo_paths=selected_photo_paths,
            downloaded_images=tuple(downloaded_images),
            primary_image_path=primary_image_path,
        )

    def _prepare_primary_only_assets(
        self,
        context: PropertyContext,
        *,
        uow: DatabaseUnitOfWork,
    ) -> PreparedMediaAssets:
        _, raw_property_dir, raw_dir, selected_dir = prepare_property_directories(
            context.storage_paths.raw_images_root,
            context.storage_paths.filtered_images_root,
            context.property,
            clear_selected_dir=True,
        )
        selected_dir.mkdir(parents=True, exist_ok=True)

        primary_source_url = context.property.featured_image_url or next(
            iter(context.property.image_urls),
            None,
        )
        if not primary_source_url:
            shutil.rmtree(raw_property_dir, ignore_errors=True)
            raise PhotoFilteringError(
                f"Property {context.property.id} does not have an image available for status reel generation.",
                code="PRIMARY_IMAGE_MISSING",
                context=build_log_context(
                    site_id=context.site_id,
                    property_id=context.property.id,
                    asset_strategy=context.delivery_plan.asset_strategy,
                ),
            )

        downloaded_images = [
            (position, image_url, None)
            for position, image_url in enumerate(context.property.image_urls, start=1)
        ]
        primary_selected_path: Path | None = None
        try:
            raw_primary_path = raw_dir / build_primary_image_filename(primary_source_url)
            download_image(primary_source_url, raw_primary_path)
            primary_selected_path = selected_dir / build_primary_image_filename(
                primary_source_url,
                raw_primary_path,
            )
            shutil.copy2(raw_primary_path, primary_selected_path)
        except Exception as exc:
            raise PhotoFilteringError(
                "Failed to prepare the primary property image for status reel rendering. "
                f"Property ID: {context.property.id} | Source URL: {primary_source_url}",
                code="PRIMARY_ASSET_DOWNLOAD_FAILED",
                context=build_log_context(
                    site_id=context.site_id,
                    property_id=context.property.id,
                    source_url=primary_source_url,
                ),
                cause=exc,
            ) from exc
        finally:
            if should_cleanup_raw_property_dir(self.cleanup_temporary_files):
                shutil.rmtree(raw_property_dir, ignore_errors=True)

        self._persist_assets(
            context=context,
            selected_dir=selected_dir,
            downloaded_images=downloaded_images,
            uow=uow,
        )

        logger.info(
            format_console_block(
                "Primary Status Reel Asset Prepared",
                format_detail_line("Site ID", context.site_id),
                format_detail_line("Property ID", context.property.id),
                format_detail_line("Selected directory", selected_dir),
                format_detail_line("Primary image", primary_selected_path or "<none>"),
                format_detail_line("Source URL", primary_source_url),
            )
        )
        return PreparedMediaAssets(
            selected_dir=selected_dir,
            selected_photo_paths=(
                (primary_selected_path,) if primary_selected_path is not None else ()
            ),
            downloaded_images=tuple(downloaded_images),
            primary_image_path=primary_selected_path,
        )

    @staticmethod
    def _persist_assets(
        *,
        context: PropertyContext,
        selected_dir: Path,
        downloaded_images: Iterable[tuple[int, str, Path | str | None]],
        uow: DatabaseUnitOfWork,
    ) -> None:
        """Idempotent re-upsert + image replacement + workflow bump."""

        normalized_external_source_id = str(context.site_id or "").strip().lower()
        property_record = _build_property_record(
            context.property,
            agency_id=context.tenant.agency_id,
            ingestion_source_id=context.tenant.wordpress_source_id,
            external_source_id=normalized_external_source_id,
            fetched_at=_now_iso(),
        )
        record_id = uow.catalog.properties.upsert_property(property_record)
        uow.catalog.images.replace_images(record_id, list(downloaded_images))
        uow.reels.states.update_workflow_state(
            agency_id=context.tenant.agency_id,
            ingestion_source_id=context.tenant.wordpress_source_id,
            external_source_id=normalized_external_source_id,
            source_property_id=context.property.id,
            workflow_state="assets_prepared",
            current_revision_id=None,
        )
        del selected_dir  # legacy receiver; modern repos don't need the path here.


__all__ = [
    "LocalPhotoSelectionEngine",
    "PrepareReelAssetsUseCase",
]
