"""Ingest a WordPress property payload into the reels pipeline.

This is step 1 of the property media pipeline (was the body of
`DefaultPropertyInfoService.ingest_property` in
`application/pipeline/media_services.py`).

Responsibilities:
  - parse the WordPress payload into a `Property` value object;
  - resolve the social-publishing inputs (target URL, generated descriptions
    + titles per platform, per-platform publish targets);
  - decide whether the reel needs new local assets / a new render / a fresh
    publish round, and which platforms are pending;
  - persist the canonical property row (`uow.catalog.properties.upsert_property`)
    and the reel pipeline state (`uow.reels.states.save`) on a fresh, modern
    `DatabaseUnitOfWork`;
  - return a legacy `PropertyContext` so steps 2/3/4 (still living in
    `application/pipeline/media_services.py`) can continue without changes.

Bridge note (Phase 2): the legacy `DefaultPropertyInfoService` adapter in
`application/pipeline/media_services.py` accepts the historic
`unit_of_work_factory` to keep the bootstrap signature stable, but that
factory is **not** consulted from this use case — feature 14 will collapse
the bridge once steps 2/3/4 also migrate.

Helpers split-out (post-review 18c, A4 ≤500 LoC):
  - `_ingest_property_planning.py`: publish-input resolution, snapshot
    builders, pending-platform diff, publish-history reset rule;
  - `_ingest_property_assets.py`: local-artefact probes, property record
    builder, next ``ReelState`` builder.
"""

from __future__ import annotations

import logging
from pathlib import Path

from modules.catalog.domain.wordpress_property import Property
from modules.reels.application.content_generator import (
    ContentGenerator,
    DeterministicPropertyContentGenerator,
)
from modules.reels.application.use_cases._ingest_property_assets import (
    _build_existing_published_media,
    _build_ingested_reel_state,
    _build_property_record,
    _has_local_artifacts,
    _should_prepare_assets,
)
from modules.reels.application.use_cases._ingest_property_diffs import (
    _coerce_publish_target_snapshot,
    _determine_pending_publish_platforms,
    _should_reset_publish_history,
)
from modules.reels.application.use_cases._ingest_property_planning import (
    _build_content_snapshot,
    _build_publish_target_snapshot,
    _json_hash,
    _json_text,
    _resolve_publish_inputs,
)
from modules.reels.domain import build_empty_reel_state
from modules.reels.domain.media_planning import build_media_delivery_plan
from modules.reels.domain.types import (
    PropertyContext,
    PropertyMediaJob,
)
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from shared.observability import format_console_block, format_detail_line
from shared.storage.site_layout import resolve_site_storage_layout

logger = logging.getLogger(__name__)


class IngestPropertyIntoReelUseCase:
    """Step 1 of the reel pipeline: ingest a property payload."""

    def __init__(
        self,
        workspace_dir: str | Path,
        *,
        property_url_template: str,
        property_url_tracking_params: dict[str, str] | None,
        social_publishing_enabled: bool,
        content_generator: ContentGenerator | None = None,
        database_locator: str | Path | None = None,
    ) -> None:
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.property_url_template = property_url_template
        self.property_url_tracking_params = dict(property_url_tracking_params or {})
        self.social_publishing_enabled = social_publishing_enabled
        self.content_generator = content_generator or DeterministicPropertyContentGenerator()
        self.database_locator = database_locator if database_locator is not None else DATABASE_URL

    def execute(
        self,
        job: PropertyMediaJob,
        *,
        uow: DatabaseUnitOfWork | None = None,
    ) -> PropertyContext:
        if uow is None:
            with DatabaseUnitOfWork(
                self.database_locator, base_dir=self.workspace_dir
            ) as managed_uow:
                return self._execute_with_uow(job, uow=managed_uow)
        return self._execute_with_uow(job, uow=uow)

    # ------------------------------------------------------------------
    # core orchestration
    # ------------------------------------------------------------------

    def _execute_with_uow(
        self,
        job: PropertyMediaJob,
        *,
        uow: DatabaseUnitOfWork,
    ) -> PropertyContext:
        if uow.catalog is None or uow.reels is None:
            raise RuntimeError("The unit of work is not active.")
        storage_paths = resolve_site_storage_layout(self.workspace_dir, job.site_id)
        property_item = Property.from_api_payload(job.payload)
        delivery_plan = build_media_delivery_plan(property_item)

        (
            publish_context,
            desired_platforms,
            publish_target_url,
            publish_descriptions_by_platform,
            publish_titles_by_platform,
            publish_targets,
        ) = _resolve_publish_inputs(
            job=job,
            property_item=property_item,
            delivery_plan=delivery_plan,
            social_publishing_enabled=self.social_publishing_enabled,
            property_url_template=self.property_url_template,
            property_url_tracking_params=self.property_url_tracking_params,
            content_generator=self.content_generator,
        )
        content_snapshot = _build_content_snapshot(
            property_item=property_item,
            delivery_plan=delivery_plan,
        )
        content_snapshot_json = _json_text(content_snapshot)
        content_fingerprint = _json_hash(content_snapshot)
        publish_target_snapshot = _build_publish_target_snapshot(
            publish_context=publish_context,
            descriptions_by_platform=publish_descriptions_by_platform,
            titles_by_platform=publish_titles_by_platform,
            publish_targets=publish_targets,
            target_url=publish_target_url,
            delivery_plan=delivery_plan,
        )
        publish_target_snapshot_json = _json_text(publish_target_snapshot)
        publish_target_fingerprint = _json_hash(publish_target_snapshot)

        normalized_external_source_id = str(job.site_id or "").strip().lower()

        property_record = _build_property_record(
            property_item,
            agency_id=job.tenant.agency_id,
            ingestion_source_id=job.tenant.wordpress_source_id,
            external_source_id=normalized_external_source_id,
            fetched_at=_now_iso(),
        )
        uow.catalog.properties.upsert_property(property_record)

        existing_state = uow.reels.states.get(
            external_source_id=normalized_external_source_id,
            source_property_id=property_item.id,
        )
        state = existing_state or build_empty_reel_state(
            external_source_id=normalized_external_source_id,
            source_property_id=property_item.id,
        )
        previous_target_snapshot = _coerce_publish_target_snapshot(
            dict(state.publish_target_snapshot or {})
        )

        has_local_artifacts = _has_local_artifacts(
            state=state,
            storage_root=self.workspace_dir,
            artifact_kind=delivery_plan.artifact_kind,
            site_id=job.site_id,
            property_slug=property_item.slug,
        )
        existing_snapshot_text = _json_text(dict(state.content_snapshot or {})) if state.content_snapshot else ""
        content_changed = (
            existing_snapshot_text != content_snapshot_json
            or state.content_fingerprint != content_fingerprint
        )
        requires_render = content_changed or not has_local_artifacts
        requires_asset_preparation = _should_prepare_assets(
            state=state,
            property_item=property_item,
            storage_paths=storage_paths,
            delivery_plan=delivery_plan,
            requires_render=requires_render,
        )
        pending_publish_platforms = _determine_pending_publish_platforms(
            state=state,
            publish_context=publish_context,
            desired_platforms=desired_platforms,
            publish_descriptions_by_platform=publish_descriptions_by_platform,
            publish_titles_by_platform=publish_titles_by_platform,
            publish_targets=publish_targets,
            publish_target_url=publish_target_url,
            delivery_plan=delivery_plan,
            requires_render=requires_render,
        )
        requires_external_publish = bool(pending_publish_platforms)
        is_noop = not requires_render and not requires_external_publish and has_local_artifacts
        existing_published_media = _build_existing_published_media(
            state=state,
            storage_root=self.workspace_dir,
        )

        if not is_noop:
            reset_publish_history = _should_reset_publish_history(
                previous_target_snapshot=previous_target_snapshot,
                publish_context=publish_context,
                requires_render=requires_render,
            )
            next_state = _build_ingested_reel_state(
                job=job,
                property_item=property_item,
                state=state,
                delivery_plan=delivery_plan,
                content_fingerprint=content_fingerprint,
                content_snapshot=content_snapshot,
                publish_target_fingerprint=publish_target_fingerprint,
                publish_target_snapshot=publish_target_snapshot,
                requires_asset_preparation=requires_asset_preparation,
                requires_render=requires_render,
                publish_context=publish_context,
                pending_publish_platforms=pending_publish_platforms,
                reset_publish_history=reset_publish_history,
                normalized_external_source_id=normalized_external_source_id,
            )
            uow.reels.states.save(next_state)

        logger.info(
            format_console_block(
                "Property Ingest Decision",
                format_detail_line("Site ID", job.site_id),
                format_detail_line("Property ID", property_item.id),
                format_detail_line("Content changed", "yes" if content_changed else "no"),
                format_detail_line("Has local artifacts", "yes" if has_local_artifacts else "no"),
                format_detail_line(
                    "Requires asset preparation",
                    "yes" if requires_asset_preparation else "no",
                ),
                format_detail_line("Requires render", "yes" if requires_render else "no"),
                format_detail_line(
                    "Pending publish platforms",
                    ", ".join(pending_publish_platforms) or "<none>",
                ),
                format_detail_line(
                    "Publish targets",
                    ", ".join(
                        f"{target.platform}:{target.artifact_kind}"
                        for target in publish_targets
                    ) or "<none>",
                ),
                format_detail_line("Noop", "yes" if is_noop else "no"),
            )
        )

        return PropertyContext(
            workspace_dir=self.workspace_dir,
            storage_paths=storage_paths,
            tenant=job.tenant,
            property=property_item,
            delivery_plan=delivery_plan,
            publish_context=publish_context,
            publish_descriptions_by_platform=publish_descriptions_by_platform,
            publish_titles_by_platform=publish_titles_by_platform,
            publish_targets=publish_targets,
            publish_target_url=publish_target_url,
            content_fingerprint=content_fingerprint,
            content_snapshot_json=content_snapshot_json,
            publish_target_fingerprint=publish_target_fingerprint,
            publish_target_snapshot_json=publish_target_snapshot_json,
            pending_publish_platforms=pending_publish_platforms,
            requires_asset_preparation=requires_asset_preparation,
            requires_render=requires_render,
            requires_external_publish=requires_external_publish,
            existing_published_media=existing_published_media,
            is_noop=is_noop,
        )


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


__all__ = ["IngestPropertyIntoReelUseCase"]
