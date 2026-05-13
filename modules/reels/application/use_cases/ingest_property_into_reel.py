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
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from modules.catalog.domain.wordpress_property import Property
from modules.configuration.application.use_cases.compute_next_publish_slot import (
    compute_next_publish_slot,
)
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
    SocialPublishContext,
)
from modules.rendering.infrastructure.render_template_settings import (
    CLASSIC_RENDER_TEMPLATE_ID,
    ResolvedRenderTemplateSettings,
    resolve_render_template_settings,
)
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from shared.errors.validation import is_valid_hex_color
from shared.observability import format_console_block, format_detail_line
from shared.storage.site_layout import (
    resolve_agency_branding_local_path,
    resolve_site_storage_layout,
)

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
        # Feature 16 (pass-2): validate the per-property accent HEX
        # fields the webhook delivers. Mirrors the warn-but-continue
        # pattern used in render_template_settings.resolve_render_template_settings
        # for an unsupported layout_variant — if a webhook ships
        # something we can't parse (CSS keyword, malformed HEX, etc.),
        # we drop the field, log a warning so operators can spot the
        # bad payload, and let the renderer fall back to
        # BrandSettings.primary_color.
        self._sanitize_property_accent_colors(property_item)
        delivery_plan = build_media_delivery_plan(property_item)
        agency_logo_local_path = self._resolve_agency_logo_local_path(
            uow=uow,
            agency_id=job.tenant.agency_id,
        )

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
        # Feature 15: compute the scheduled publish slot for the webhook
        # auto-publish flow. ``compute_next_publish_slot`` returns ``None``
        # for "publish immediately"; otherwise the use case forwards the
        # slot down the ``SocialPublishContext`` so the downstream GHL POST
        # emits ``scheduleDate`` and ``status='scheduled'``. The
        # ``approval_required=True`` case still parks the reel pending the
        # manual approve without consulting this slot —
        # ``regenerate_reel.py`` (feature 11/14) computes its own slot at
        # approve time.
        publish_context = self._apply_scheduled_publish_slot(
            uow=uow,
            agency_id=job.tenant.agency_id,
            publish_context=publish_context,
        )
        render_template_settings = self._resolve_render_template_settings(
            uow=uow,
            agency_id=job.tenant.agency_id,
            publish_context=publish_context or job.publish_context,
        )
        # Feature 16: pre-resolve the agency BrandSettings.primary_color
        # fallback used by the side_banner render template when a
        # property webhook does not carry its own wppd_accent_*. Both
        # accent colors fall back to the same primary_color per product
        # decision; the renderer can still distinguish them because text
        # and background are drawn from different fields.
        brand_fallback_color = self._resolve_brand_primary_color(
            uow=uow,
            agency_id=job.tenant.agency_id,
        )
        render_template_reel_settings = dict(render_template_settings.reel_settings)
        render_template_poster_settings = dict(render_template_settings.poster_settings)
        if brand_fallback_color:
            render_template_reel_settings.setdefault(
                "fallback_accent_text_color", brand_fallback_color
            )
            render_template_reel_settings.setdefault(
                "fallback_accent_background_color", brand_fallback_color
            )
            render_template_poster_settings.setdefault(
                "fallback_accent_text_color", brand_fallback_color
            )
            render_template_poster_settings.setdefault(
                "fallback_accent_background_color", brand_fallback_color
            )
        content_snapshot = _build_content_snapshot(
            property_item=property_item,
            delivery_plan=delivery_plan,
            render_template_snapshot={
                "template_id": render_template_settings.template_id,
                "layout_variant": render_template_settings.layout_variant,
                "settings_hash": render_template_settings.settings_hash,
            },
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
        existing_snapshot_text = (
            _json_text(dict(state.content_snapshot or {}))
            if state.content_snapshot
            else ""
        )
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
                render_template_id=render_template_settings.template_id,
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
            render_template_id=render_template_settings.template_id,
            render_template_settings_hash=render_template_settings.settings_hash,
            render_template_layout_variant=render_template_settings.layout_variant,
            render_template_reel_settings=render_template_reel_settings,
            render_template_poster_settings=render_template_poster_settings,
            pending_publish_platforms=pending_publish_platforms,
            requires_asset_preparation=requires_asset_preparation,
            requires_render=requires_render,
            requires_external_publish=requires_external_publish,
            existing_published_media=existing_published_media,
            is_noop=is_noop,
            agency_logo_local_path=agency_logo_local_path,
        )

    def _resolve_render_template_settings(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
        publish_context: SocialPublishContext | None,
    ) -> ResolvedRenderTemplateSettings:
        requested_template_id = (
            publish_context.render_template_id if publish_context is not None else ""
        )
        configuration = getattr(uow, "configuration", None)
        template_repository = (
            getattr(configuration, "render_templates", None)
            if configuration is not None
            else None
        )
        defaults_repository = (
            getattr(configuration, "defaults", None)
            if configuration is not None
            else None
        )
        if not requested_template_id and defaults_repository is not None:
            defaults = defaults_repository.get(str(agency_id or "").strip())
            if defaults is not None:
                requested_template_id = getattr(
                    defaults,
                    "render_template_id",
                    CLASSIC_RENDER_TEMPLATE_ID,
                )
        requested_template_id = (
            str(requested_template_id or "").strip() or CLASSIC_RENDER_TEMPLATE_ID
        )
        if template_repository is None:
            return resolve_render_template_settings(None)

        template = template_repository.get(requested_template_id)
        if template is None and requested_template_id != CLASSIC_RENDER_TEMPLATE_ID:
            logger.warning(
                "Selected render template %s is missing for agency %s; falling back to classic.",
                requested_template_id,
                agency_id,
            )
            template = template_repository.get(CLASSIC_RENDER_TEMPLATE_ID)
        if template is None:
            logger.warning(
                "Classic render template is missing; using built-in classic defaults."
            )
        return resolve_render_template_settings(template)

    def _apply_scheduled_publish_slot(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
        publish_context: SocialPublishContext | None,
    ) -> SocialPublishContext | None:
        """Compute ``scheduled_at`` and stamp it on ``publish_context``.

        Feature 15: the webhook auto-publish flow must honour the
        Automation window the same way the manual approve flow does
        (feature 11/14). We load the agency's ``AutomationRules`` plus
        IANA ``timezone`` and delegate the slot computation to the pure
        :func:`compute_next_publish_slot` use case.

        Returns the (possibly replaced) ``SocialPublishContext`` so the
        caller can pass it through the rest of the ingest pipeline. The
        method is defensive on three axes so unit-test UoWs that omit
        the ``configuration`` / ``tenancy`` namespaces keep working:

        * ``uow.configuration.automation`` missing → no rules → slot is
          ``None`` → publish_context unchanged (legacy "immediate"
          contract).
        * ``uow.tenancy.agencies`` missing or no timezone → fall back to
          UTC.
        * ``publish_context is None`` (``social_publishing_enabled=False``
          or the job arrived without one) → returned as-is, no
          ``dataclasses.replace(None, ...)`` crash.

        ``approval_required`` is **not** consulted here: the slot is
        cheap to compute and stamping it on the context lets the manual
        approve flow inspect/override it later. The downstream
        ``regenerate_reel.py`` (feature 11/14) computes its own slot at
        approve time so the value persisted here is only authoritative
        for the auto-publish branch.
        """
        configuration_module = getattr(uow, "configuration", None)
        automation_repository = (
            getattr(configuration_module, "automation", None)
            if configuration_module is not None
            else None
        )
        tenancy_module = getattr(uow, "tenancy", None)
        agency_repository = (
            getattr(tenancy_module, "agencies", None)
            if tenancy_module is not None
            else None
        )
        automation_rules = (
            automation_repository.get(agency_id)
            if automation_repository is not None
            else None
        )
        agency_record = (
            agency_repository.get_by_id(agency_id)
            if agency_repository is not None
            else None
        )
        agency_timezone = (
            agency_record.timezone
            if agency_record is not None and getattr(agency_record, "timezone", "")
            else "UTC"
        )
        scheduled_slot = compute_next_publish_slot(
            automation_rules,
            datetime.now(timezone.utc),
            agency_timezone=agency_timezone,
        )
        scheduled_at_iso: str | None = (
            scheduled_slot.isoformat() if scheduled_slot is not None else None
        )
        if publish_context is not None and scheduled_at_iso is not None:
            return replace(publish_context, scheduled_at=scheduled_at_iso)
        return publish_context

    @staticmethod
    def _sanitize_property_accent_colors(property_item: Property) -> None:
        """Drop malformed accent HEX values and log a warning.

        Feature 16 (pass-2): the WordPress webhook may deliver CSS
        keywords (``"red"``) or malformed strings (``"#xyz"``) for the
        accent fields. The downstream ffmpeg ``drawbox`` / ``drawtext``
        filters silently swallow such values, which makes the bug hard
        to spot. We validate up front via
        :func:`shared.errors.validation.is_valid_hex_color`; an invalid
        value is logged at ``WARNING`` level (so operators can correlate
        the bad payload with the rendered output) and the field is
        nulled so the renderer falls back to
        ``BrandSettings.primary_color`` like a property that never
        provided the field.

        ``None`` and missing values pass through untouched — they are
        the legitimate "field absent" signal.
        """
        for field_name in ("wppd_accent_text_color", "wppd_accent_background_color"):
            raw_value = getattr(property_item, field_name, None)
            if raw_value is None:
                continue
            if is_valid_hex_color(raw_value):
                continue
            logger.warning(
                "Property %s carries invalid HEX color in %s=%r; falling back to "
                "BrandSettings.primary_color.",
                property_item.id,
                field_name,
                raw_value,
            )
            setattr(property_item, field_name, None)

    def _resolve_brand_primary_color(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
    ) -> str | None:
        """Resolve the agency BrandSettings.primary_color for accent fallback.

        Feature 16: when a WordPress property webhook omits
        ``wppd_accent_text_color`` / ``wppd_accent_background_color``,
        the side_banner renderer falls back to this color for both
        accent fields (per product decision). The lookup is best-effort
        — unit-test UoWs that omit ``configuration`` or its ``brand``
        repo get ``None`` and the renderer then falls back to its own
        built-in defaults (``#0F172A`` for text, ``#FFFFFF`` for
        background).
        """
        normalized_agency_id = str(agency_id or "").strip()
        if not normalized_agency_id:
            return None
        configuration = getattr(uow, "configuration", None)
        if configuration is None:
            return None
        brand_repo = getattr(configuration, "brand", None)
        if brand_repo is None:
            return None
        brand = brand_repo.get(normalized_agency_id)
        if brand is None:
            return None
        primary_color = str(getattr(brand, "primary_color", "") or "").strip()
        return primary_color or None

    def _resolve_agency_logo_local_path(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
    ) -> Path | None:
        """Resolve the agency's uploaded logo path, if any.

        Reads ``agency_brand_settings.logo_object_key`` (feature 10) and
        resolves it to an on-disk path under
        ``workspace_dir/generated_media/_agency_branding/``. Returns
        ``None`` when the key is empty, when the agency has no brand row
        yet, or when the referenced file is missing on disk — the
        renderer falls back to ``property.agency_logo_url`` in that
        case.

        The lookup is best-effort: unit-test UoWs that omit the
        ``configuration`` namespace still get a clean ``None`` without
        the ingest having to be reshaped.
        """
        normalized_agency_id = str(agency_id or "").strip()
        if not normalized_agency_id:
            return None
        configuration = getattr(uow, "configuration", None)
        if configuration is None:
            return None
        brand_repo = getattr(configuration, "brand", None)
        if brand_repo is None:
            return None
        brand = brand_repo.get(normalized_agency_id)
        if brand is None:
            return None
        object_key = str(getattr(brand, "logo_object_key", "") or "").strip()
        if not object_key:
            return None
        return resolve_agency_branding_local_path(
            workspace_dir=self.workspace_dir,
            object_key=object_key,
        )


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


__all__ = ["IngestPropertyIntoReelUseCase"]
