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
from typing import Any

from modules.catalog.domain.wordpress_property import Property
from modules.configuration.application.use_cases.compute_next_publish_slot import (
    compute_next_publish_slot,
)
from modules.configuration.application.use_cases.read_aggregated_reel_profile import (
    resolve_music_selection_rules,
)
from modules.configuration.domain import font_catalog
from modules.configuration.domain.font_catalog import FontDescriptor
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
from modules.reels.application.use_cases._resolve_agency_music_pool import (
    resolve_agency_background_audio_candidates,
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
    resolve_agency_intro_outro_local_path,
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
        # HOTFIX 2026-05-15: per-agency switch to hide the listing agent
        # photo from the rendered reel. The flag rides on the JSONB
        # ``agency_reel_defaults.settings`` column under
        # ``showAgentPhoto`` (camelCase to match the frontend
        # INITIAL_DEFAULTS shape; default True preserves current
        # behaviour for every agency that has not flipped the toggle).
        # Anulating ``agent_photo_url`` here keeps the rest of the
        # pipeline untouched: ``prepare_agent_image`` already
        # short-circuits on a falsy URL (runtime/branding.py:125).
        if not self._resolve_show_agent_photo(
            uow=uow, agency_id=job.tenant.agency_id
        ):
            property_item.agent_photo_url = None
        delivery_plan = build_media_delivery_plan(property_item)
        agency_logo_local_path = self._resolve_agency_logo_local_path(
            uow=uow,
            agency_id=job.tenant.agency_id,
        )
        outro_local_path, outro_source, outro_duration_seconds = (
            self._resolve_agency_outro_asset(
                uow=uow,
                agency_id=job.tenant.agency_id,
            )
        )
        intro_local_path, intro_source, intro_duration_seconds = (
            self._resolve_agency_intro_asset(
                uow=uow,
                agency_id=job.tenant.agency_id,
            )
        )
        # Feature 23: resolve the agency-scoped pool of background audio
        # tracks ahead of the render. ``agency_music_tracks`` is the
        # canonical source post-feature-23 (the seed migration backfills
        # NCS defaults per agency); the runtime renderer falls back to
        # ``assets/music/`` only when this tuple is empty, which now
        # only happens in unit-test UoWs that omit ``configuration``.
        #
        # Feature 24: honour the persisted
        # ``settings.music.selection_rules.fallback_to_full_library``
        # flag. The pre-feature-24 hardcoded ``True`` is preserved by
        # ``resolve_music_selection_rules`` when the agency has never
        # set the toggle (the default value is not persisted on save,
        # only applied on read).
        music_selection_rules = self._resolve_music_selection_rules(
            uow=uow,
            agency_id=job.tenant.agency_id,
        )
        background_audio_candidates = resolve_agency_background_audio_candidates(
            uow=uow,
            agency_id=job.tenant.agency_id,
            workspace_dir=self.workspace_dir,
            fallback_to_full_library=bool(
                music_selection_rules.get("fallback_to_full_library", True)
            ),
        )
        # Feature 25: when the job carries ``override_music_track_id`` on
        # the publish_context, swap the agency-pool tuple for the single
        # overridden track. If the override id no longer resolves (the
        # agency deleted the track between the PATCH and the render —
        # ``ON DELETE SET NULL`` already wiped ``reels.music_id`` but the
        # in-flight job keeps the old id) we fall back to the resolved
        # default pool with a warning instead of failing the render.
        background_audio_candidates = self._apply_music_track_override(
            uow=uow,
            agency_id=job.tenant.agency_id,
            publish_context=job.publish_context,
            background_audio_candidates=background_audio_candidates,
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
        # Hotfix 2026-05-15: side_banner colours come exclusively from
        # the agency brand row. The legacy ``fallback_accent_*_color``
        # keys (feature 16) used to be injected here as a fallback for
        # the WordPress webhook accents, but the webhook feed is no
        # longer consulted at render time. The renderer falls back to
        # hardcoded neutral greys when the brand has no override.
        brand_primary_color = self._resolve_brand_primary_color(
            uow=uow,
            agency_id=job.tenant.agency_id,
        )
        brand_secondary_color = self._resolve_brand_secondary_color(
            uow=uow,
            agency_id=job.tenant.agency_id,
        )
        # Feature 28: resolve the agency BrandSettings.font_family to a
        # FontDescriptor and inject its TTF paths into the renderer
        # template overrides. The descriptor lives in
        # ``modules.configuration.domain.font_catalog`` and falls back
        # to Inter when the agency has no override (or persisted a
        # family that has since been retired from the catalogue — the
        # resolver logs a warning instead of crashing the render).
        font_descriptor = self._resolve_brand_font_descriptor(
            uow=uow,
            agency_id=job.tenant.agency_id,
        )
        render_template_reel_settings = dict(render_template_settings.reel_settings)
        render_template_poster_settings = dict(render_template_settings.poster_settings)
        if brand_primary_color:
            # ``side_banner_panel_color`` drives the top / bottom panels
            # of the side_banner template in both reel and poster. The
            # renderer falls back to a hardcoded neutral grey if this
            # value is not set.
            render_template_reel_settings.setdefault(
                "side_banner_panel_color", brand_primary_color
            )
            render_template_poster_settings.setdefault(
                "side_banner_panel_color", brand_primary_color
            )
        if brand_secondary_color:
            # ``side_banner_ribbon_background_color`` drives the rotated
            # status ribbon (only the reel uses it; the poster does not
            # render the ribbon asset). Renderer fallback is the grey
            # ``_SIDE_BANNER_RIBBON_BACKGROUND`` in ``preparation.py``.
            render_template_reel_settings.setdefault(
                "side_banner_ribbon_background_color",
                brand_secondary_color,
            )
        # Feature 31: stash the per-agency subtitle styling persisted on
        # ``agency_reel_defaults.settings`` under renderer-internal
        # snake_case keys on ``render_template_reel_settings``. The
        # frontend persists camelCase ``sub*`` plus a dotted
        # ``automation.autoCaptions`` flag; the translation here keeps
        # the renderer free of camelCase. Only the reel consumes the
        # subtitle settings — posters never render captions — so the
        # poster overrides dict is intentionally left alone.
        subtitle_overrides = self._resolve_subtitle_settings_overrides(
            uow=uow,
            agency_id=job.tenant.agency_id,
        )
        for snake_key, value in subtitle_overrides.items():
            render_template_reel_settings.setdefault(snake_key, value)
        # The font override always wins over the template default — a
        # template still ships its own ``font_path`` for legacy reasons,
        # but the brand setting is the canonical source for the heading
        # weight at render time. ``property_reel_template_to_dict``
        # serialises the Path as ``str``; the renderer rebuilds it via
        # ``build_property_reel_template_from_overrides`` (Path coercion
        # in ``_coerce_template_value``) so the str form here matches
        # the rest of the dict's payload.
        render_template_reel_settings["font_path"] = str(
            font_descriptor.regular_path
        )
        render_template_reel_settings["bold_font_path"] = str(
            font_descriptor.bold_path
        )
        render_template_poster_settings["font_path"] = str(
            font_descriptor.regular_path
        )
        render_template_poster_settings["bold_font_path"] = str(
            font_descriptor.bold_path
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
        # Feature 21: apply any per-reel description override on top of
        # the freshly-templated captions before they enter the publish
        # target snapshot or the PropertyContext that the worker forwards
        # to the social publisher. The override is read from the previously
        # persisted ReelState (loaded immediately below). The mapping is
        # ``platform → rendered caption text``; per-platform ``None`` /
        # empty values fall back to the templated text so a partial edit
        # cannot silently wipe out untouched platforms.
        _peeked_existing_state = uow.reels.states.get(
            external_source_id=str(job.site_id or "").strip().lower(),
            source_property_id=property_item.id,
        )
        _apply_descriptions_override(
            publish_descriptions_by_platform,
            override=(
                _peeked_existing_state.descriptions_override
                if _peeked_existing_state is not None
                else None
            ),
        )
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

        # The state was already fetched above to peek at the
        # ``descriptions_override`` (feature 21). Reuse it so we don't
        # round-trip the same row twice in a single ingest pass.
        existing_state = _peeked_existing_state
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
        # Política 2026-05-19: cada webhook de ingest dispara render
        # incondicionalmente. El content fingerprint no entra en el
        # catálogo de brand/subtitle overrides (font_family, colores,
        # subtítulos) — antes de este cambio cambiar la fuente brand no
        # movía el fingerprint y la pipeline reutilizaba el MP4 antiguo
        # via "EXISTING MEDIA PUBLISH" fast-path. El usuario prefiere
        # pagar el coste de un render por webhook a tener artefactos
        # stale. El endpoint manual `regenerate` (feature 40) usa otro
        # use case y no se ve afectado.
        requires_render = True
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
            background_audio_candidates=background_audio_candidates,
            outro_local_path=outro_local_path,
            outro_source=outro_source,
            outro_duration_seconds=outro_duration_seconds,
            intro_local_path=intro_local_path,
            intro_source=intro_source,
            intro_duration_seconds=intro_duration_seconds,
            # Feature 35: forward the persisted per-reel photo override
            # (if any) so the renderer can reorder / filter the source
            # photos when building the manifest. ``None`` means "no
            # override — render in the default property_images order".
            photos_override=_coerce_photos_override(
                _peeked_existing_state.photos_override
                if _peeked_existing_state is not None
                else None
            ),
            # Feature 36: forward the persisted per-reel subtitles
            # override. ``None`` means "no override — keep the existing
            # autoCaptions flow". Otherwise a tuple of cue tuples
            # consumed by the renderer to build the subtitle drawtext
            # directly, bypassing ``compose_subtitle_segments``.
            subtitles_override=_coerce_subtitles_override(
                _peeked_existing_state.subtitles_override
                if _peeked_existing_state is not None
                else None
            ),
            # Feature 37: forward the persisted per-reel slide manifest
            # override. ``None`` means "no override — fall back to the
            # auto-generated manifest pipeline". Otherwise the
            # validated tuple of slide dicts drives the scene list
            # directly.
            manifest_override=_coerce_manifest_override(
                _peeked_existing_state.manifest_override
                if _peeked_existing_state is not None
                else None
            ),
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

    def _apply_music_track_override(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
        publish_context: SocialPublishContext | None,
        background_audio_candidates: tuple[Path, ...],
    ) -> tuple[Path, ...]:
        """Swap the resolved pool for the per-reel music override (feature 25).

        When the job carries an ``override_music_track_id`` we look the
        track up in ``agency_music_tracks`` and rebuild the candidate
        tuple as a single-element list. Three guards keep the override
        layer safe:

        * the override is ignored for jobs without ``publish_context``
          (pre-feature-25, or ``social_publishing_enabled=False``);
        * a track that no longer exists or belongs to a different agency
          falls back to the resolved pool with a warning — this handles
          the race where the agency deletes the track between the PATCH
          and the render (``reels.music_id`` is already NULL via
          ``ON DELETE SET NULL`` but the in-flight job still carries the
          old id);
        * a unit-test UoW without ``configuration.music`` short-circuits
          to the pre-override pool, mirroring the rest of the music
          resolver helpers.
        """
        if publish_context is None:
            return background_audio_candidates
        override_id = (
            str(publish_context.override_music_track_id or "").strip()
            if publish_context.override_music_track_id is not None
            else ""
        )
        if not override_id:
            return background_audio_candidates
        configuration = getattr(uow, "configuration", None)
        if configuration is None:
            return background_audio_candidates
        music_repo = getattr(configuration, "music", None)
        if music_repo is None:
            return background_audio_candidates
        track = music_repo.get(music_id=override_id)
        normalized_agency_id = str(agency_id or "").strip()
        if track is None or str(track.agency_id).strip() != normalized_agency_id:
            logger.warning(
                "Music override %s no longer resolves for agency %s; "
                "falling back to the resolved pool.",
                override_id,
                normalized_agency_id,
            )
            return background_audio_candidates
        # Local import keeps the rendering-runtime helper from being
        # eagerly imported at module top-level — matches the layered
        # access already in ``_resolve_agency_music_pool``.
        from modules.rendering.infrastructure.runtime.assets import (
            resolve_agency_music_local_paths,
        )

        return resolve_agency_music_local_paths(
            workspace_dir=self.workspace_dir,
            music_tracks=(track,),
        )

    def _resolve_music_selection_rules(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
    ) -> dict:
        """Load ``settings.music.selection_rules`` for the agency.

        Feature 24: ``agency_reel_defaults.settings`` is the canonical
        bucket for the music selection rules (the JSONB column already
        exists; only the sub-key is new). The helper defensively walks
        ``uow.configuration.defaults`` so unit-test UoWs that omit the
        namespace still get the documented default
        (``fallback_to_full_library=True``) without the ingest having to
        be reshaped.
        """
        normalized_agency_id = str(agency_id or "").strip()
        if not normalized_agency_id:
            return resolve_music_selection_rules(None)
        configuration = getattr(uow, "configuration", None)
        if configuration is None:
            return resolve_music_selection_rules(None)
        defaults_repo = getattr(configuration, "defaults", None)
        if defaults_repo is None:
            return resolve_music_selection_rules(None)
        defaults = defaults_repo.get(normalized_agency_id)
        if defaults is None:
            return resolve_music_selection_rules(None)
        return resolve_music_selection_rules(
            getattr(defaults, "settings", None)
        )

    def _resolve_show_agent_photo(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
    ) -> bool:
        """Return ``False`` only when the agency explicitly hid the agent photo.

        HOTFIX 2026-05-15: the ``/brand`` page exposes a switch that
        persists ``showAgentPhoto`` inside the JSONB
        ``agency_reel_defaults.settings`` column (no Alembic migration —
        the column is shared with subtitle/music settings since features
        24 and 31). Defensive on the same axes as the other
        ``_resolve_*`` helpers so unit-test UoWs that omit
        ``configuration`` / ``defaults`` keep the historical behaviour
        of rendering the agent photo.
        """
        normalized_agency_id = str(agency_id or "").strip()
        if not normalized_agency_id:
            return True
        configuration = getattr(uow, "configuration", None)
        if configuration is None:
            return True
        defaults_repo = getattr(configuration, "defaults", None)
        if defaults_repo is None:
            return True
        defaults = defaults_repo.get(normalized_agency_id)
        if defaults is None:
            return True
        settings_dict = getattr(defaults, "settings", None) or {}
        if not isinstance(settings_dict, dict):
            return True
        value = settings_dict.get("showAgentPhoto")
        if value is None:
            return True
        return bool(value)

    def _resolve_subtitle_settings_overrides(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
    ) -> dict[str, object]:
        """Translate per-agency subtitle settings into renderer-internal keys.

        Feature 31: the frontend ``/defaults > Subtitles`` panel persists
        ten ``sub*`` fields (camelCase) plus a dotted
        ``automation.autoCaptions`` flag inside the JSONB
        ``agency_reel_defaults.settings`` column. The renderer talks
        snake_case, so this helper maps the persisted shape into the
        renderer-internal override keys that ride along in
        ``render_template_reel_settings`` and are read back by
        ``frame_composition._build_render_data`` to build the
        ``SubtitleStyle`` dataclass.

        Defensive on the same axes as the other ``_resolve_*`` helpers:

        * Unit-test UoWs that omit ``configuration`` / ``defaults`` → no
          overrides; the renderer falls back to ``SubtitleStyle()``
          defaults (the historical look).
        * Agency without a defaults row → empty dict, same fallback.
        * Missing camelCase keys → only the present ones are forwarded
          (``setdefault`` in the caller preserves any value already
          stashed by another cascade).
        """
        normalized_agency_id = str(agency_id or "").strip()
        if not normalized_agency_id:
            return {}
        configuration = getattr(uow, "configuration", None)
        if configuration is None:
            return {}
        defaults_repo = getattr(configuration, "defaults", None)
        if defaults_repo is None:
            return {}
        defaults = defaults_repo.get(normalized_agency_id)
        if defaults is None:
            return {}
        settings_dict = getattr(defaults, "settings", None) or {}
        if not isinstance(settings_dict, dict):
            return {}
        overrides: dict[str, object] = {}
        sub_camel_to_snake = {
            "subFont": "subtitle_font_family",
            "subWeight": "subtitle_weight",
            "subColor": "subtitle_color",
            "subBgStyle": "subtitle_bg_style",
            "subBgColor": "subtitle_bg_color",
            "subBgOpacity": "subtitle_bg_opacity",
            "subPosition": "subtitle_position",
            "subAlign": "subtitle_alignment",
            "subUppercase": "subtitle_uppercase",
            "subMaxChars": "subtitle_max_chars",
        }
        for camel_key, snake_key in sub_camel_to_snake.items():
            if camel_key in settings_dict:
                overrides[snake_key] = settings_dict[camel_key]
        auto_captions = settings_dict.get("automation.autoCaptions")
        if auto_captions is not None:
            overrides["auto_captions_enabled"] = bool(auto_captions)
        return overrides

    def _resolve_brand_font_descriptor(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
    ) -> FontDescriptor:
        """Resolve the agency BrandSettings.font_family to a catalogue entry.

        Feature 28: the brand selector lets agencies pick a font from the
        catalogue defined in
        :mod:`modules.configuration.domain.font_catalog`. The persisted
        family is opaque to the renderer; this helper translates it back
        to the canonical descriptor (regular + bold TTF paths) so the
        ingest can inject them into ``render_template_reel_settings``.

        Defensive on three axes:

        * Unit-test UoWs that omit ``configuration`` / ``brand`` → fall
          back to ``DEFAULT_FONT_FAMILY`` (Inter) without raising.
        * Agency persisted ``font_family=NULL`` (the documented "use the
          renderer default" signal) → also fall back to Inter.
        * Agency persisted a family that has since been removed from the
          catalogue → warn and fall back to Inter so the render does
          not crash on a stale value. Operators see the warning in the
          worker logs.
        """
        normalized_agency_id = str(agency_id or "").strip()
        if not normalized_agency_id:
            return font_catalog.resolve(None)
        configuration = getattr(uow, "configuration", None)
        if configuration is None:
            return font_catalog.resolve(None)
        brand_repo = getattr(configuration, "brand", None)
        if brand_repo is None:
            return font_catalog.resolve(None)
        brand = brand_repo.get(normalized_agency_id)
        if brand is None:
            return font_catalog.resolve(None)
        family = str(getattr(brand, "font_family", "") or "").strip() or None
        try:
            return font_catalog.resolve(family)
        except ValueError:
            logger.warning(
                "Agency %s brand.font_family=%r is not in the catalogue; "
                "falling back to %s.",
                normalized_agency_id,
                family,
                font_catalog.DEFAULT_FONT_FAMILY,
            )
            return font_catalog.resolve(None)

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

    def _resolve_brand_secondary_color(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
    ) -> str | None:
        """Resolve ``BrandSettings.secondary_color`` for the side_banner ribbon.

        Feature 29: when an agency has configured a brand secondary
        color, the side_banner vertical ribbon switches its background
        from the hardcoded global default (``#FECF4D``, introduced by
        feature 17) to the brand color. The WordPress webhook does not
        currently carry a "secondary" accent — ``wppd_accent_text_color``
        and ``wppd_accent_background_color`` are the primary accent pair
        — so the cascade collapses to two levels:

        1. ``BrandSettings.secondary_color`` (per-agency override);
        2. ``preparation._SIDE_BANNER_RIBBON_BACKGROUND`` (``#FECF4D``,
           applied by the renderer when this helper returns ``None``).

        Defensive on the same axes as ``_resolve_brand_primary_color``:
        unit-test UoWs that omit ``configuration`` / ``brand``, agencies
        without a brand row, or agencies persisting an empty / blank
        value all yield ``None`` so the renderer keeps the historical
        ``#FECF4D`` fallback.

        Hex validation is intentionally delegated to the rendering layer
        (``apply_alpha_to_hex`` already returns ``None`` for malformed
        values and the helper has a hardcoded default to fall back to);
        the brand router validates on PUT so persisted values are
        normalized HEX by the time we read them here.
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
        secondary_color = str(getattr(brand, "secondary_color", "") or "").strip()
        return secondary_color or None

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

    def _resolve_agency_outro_asset(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
    ) -> tuple[Path | None, str, int]:
        """Resolve the agency outro asset for the render pipeline.

        Returns ``(local_path, source, duration_seconds)``:

        * ``local_path`` — on-disk file when ``source='uploaded'`` AND
          ``outro_enabled=True`` AND the blob is present. ``None`` in
          every other case (including ``brand_card``, which is reserved
          for a future feature and treated as a no-op today — see
          feature 33 leader brief).
        * ``source`` — verbatim from the ``agency_intro_outro_assets``
          row (``'uploaded' | 'brand_card' | 'none'``). Defaults to
          ``'none'`` when no row exists.
        * ``duration_seconds`` — only populated when the concat will
          actually happen; ``0`` otherwise.

        Best-effort: unit-test UoWs that omit ``configuration`` /
        ``intro_outro_assets`` cleanly yield ``(None, 'none', 0)``.
        """
        normalized_agency_id = str(agency_id or "").strip()
        if not normalized_agency_id:
            return (None, "none", 0)
        configuration = getattr(uow, "configuration", None)
        if configuration is None:
            return (None, "none", 0)
        defaults_repo = getattr(configuration, "defaults", None)
        outro_repo = getattr(configuration, "intro_outro_assets", None)
        if outro_repo is None:
            return (None, "none", 0)
        defaults = defaults_repo.get(normalized_agency_id) if defaults_repo is not None else None
        outro_enabled = bool(getattr(defaults, "outro_enabled", False)) if defaults else False
        asset = outro_repo.get(agency_id=normalized_agency_id, kind="outro")
        if asset is None:
            return (None, "none", 0)
        if asset.source == "brand_card":
            logger.warning(
                "Outro source 'brand_card' is reserved for a future feature; "
                "skipping concat for agency=%s",
                normalized_agency_id,
            )
            return (None, asset.source, 0)
        if asset.source != "uploaded" or not outro_enabled or not asset.object_key:
            return (None, asset.source, 0)
        local_path = resolve_agency_intro_outro_local_path(
            workspace_dir=self.workspace_dir,
            object_key=asset.object_key,
        )
        if local_path is None:
            logger.warning(
                "Outro blob missing on disk for agency=%s object_key=%s; "
                "skipping outro concat.",
                normalized_agency_id,
                asset.object_key,
            )
            return (None, asset.source, 0)
        return (local_path, asset.source, int(asset.duration_seconds or 0))

    def _resolve_agency_intro_asset(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
    ) -> tuple[Path | None, str, int]:
        """Resolve the agency intro asset for the render pipeline.

        Feature 34: symmetric to :meth:`_resolve_agency_outro_asset`.

        Returns ``(local_path, source, duration_seconds)``:

        * ``local_path`` — on-disk file when ``source='uploaded'`` AND
          ``intro_enabled=True`` AND the blob is present. ``None`` in
          every other case (including ``brand_card``, which is reserved
          for a future feature and treated as a no-op today).
        * ``source`` — verbatim from the ``agency_intro_outro_assets``
          row (``'uploaded' | 'brand_card' | 'none'``). Defaults to
          ``'none'`` when no row exists.
        * ``duration_seconds`` — only populated when the concat will
          actually happen; ``0`` otherwise.

        Best-effort: unit-test UoWs that omit ``configuration`` /
        ``intro_outro_assets`` cleanly yield ``(None, 'none', 0)``.
        """
        normalized_agency_id = str(agency_id or "").strip()
        if not normalized_agency_id:
            return (None, "none", 0)
        configuration = getattr(uow, "configuration", None)
        if configuration is None:
            return (None, "none", 0)
        defaults_repo = getattr(configuration, "defaults", None)
        intro_repo = getattr(configuration, "intro_outro_assets", None)
        if intro_repo is None:
            return (None, "none", 0)
        defaults = defaults_repo.get(normalized_agency_id) if defaults_repo is not None else None
        # ``intro_enabled`` already exists on ``agency_reel_defaults`` from
        # the initial migration; defaults to True so historical agencies
        # keep their intro flow until they opt out. The concat helper only
        # actually runs when the agency *also* uploaded a video — the
        # ``intro_enabled`` flag with no uploaded asset still skips the
        # concat (the legacy intro card is rendered by a different path).
        intro_enabled = bool(getattr(defaults, "intro_enabled", True)) if defaults else True
        asset = intro_repo.get(agency_id=normalized_agency_id, kind="intro")
        if asset is None:
            return (None, "none", 0)
        if asset.source == "brand_card":
            logger.warning(
                "Intro source 'brand_card' is reserved for a future feature; "
                "skipping concat for agency=%s",
                normalized_agency_id,
            )
            return (None, asset.source, 0)
        if asset.source != "uploaded" or not intro_enabled or not asset.object_key:
            return (None, asset.source, 0)
        local_path = resolve_agency_intro_outro_local_path(
            workspace_dir=self.workspace_dir,
            object_key=asset.object_key,
        )
        if local_path is None:
            logger.warning(
                "Intro blob missing on disk for agency=%s object_key=%s; "
                "skipping intro concat.",
                normalized_agency_id,
                asset.object_key,
            )
            return (None, asset.source, 0)
        return (local_path, asset.source, int(asset.duration_seconds or 0))


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _coerce_photos_override(
    raw,
) -> tuple[tuple[int, bool], ...] | None:
    """Coerce the persisted ``reels.photos_override`` into a render-time tuple.

    Feature 35: the JSONB column persists a list of ``{position, selected}``
    dicts. The renderer prefers an immutable ``tuple[(int, bool), ...]``
    so :class:`PropertyContext` can stay ``frozen``. ``None``, empty
    lists and malformed entries collapse to ``None`` so the renderer
    falls back to the default order without raising.
    """
    if not raw:
        return None
    if not isinstance(raw, (list, tuple)):
        return None
    coerced: list[tuple[int, bool]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            position = int(entry["position"])
            selected = bool(entry["selected"])
        except (KeyError, TypeError, ValueError):
            continue
        coerced.append((position, selected))
    return tuple(coerced) if coerced else None


def _coerce_subtitles_override(
    raw,
) -> tuple[tuple[int, str, float, float], ...] | None:
    """Coerce the persisted ``reels.subtitles_override`` into a render-time tuple.

    Feature 36: the JSONB column persists a list of
    ``{index, text, in_seconds, out_seconds}`` dicts. The renderer
    prefers an immutable ``tuple[(int, str, float, float), ...]`` so
    :class:`PropertyContext` can stay ``frozen``. ``None``, empty lists
    and malformed entries collapse to ``None`` so the renderer falls
    back to the autoCaptions flow without raising. The PATCH layer
    enforces uniqueness / monotonicity / non-overlap; here we only
    decode types defensively.
    """
    if not raw:
        return None
    if not isinstance(raw, (list, tuple)):
        return None
    coerced: list[tuple[int, str, float, float]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            index = int(entry["index"])
            text_value = str(entry["text"])
            in_seconds = float(entry["in_seconds"])
            out_seconds = float(entry["out_seconds"])
        except (KeyError, TypeError, ValueError):
            continue
        coerced.append((index, text_value, in_seconds, out_seconds))
    return tuple(coerced) if coerced else None


def _coerce_manifest_override(
    raw,
) -> tuple[dict[str, Any], ...] | None:
    """Coerce the persisted ``reels.manifest_override`` into a tuple.

    Feature 37: the JSONB column persists a list of slide dicts whose
    shape was already validated at the PATCH layer (discriminated
    union, position coverage, duration cap, unique slide_id). The
    renderer prefers an immutable tuple so :class:`PropertyContext` can
    stay ``frozen``. ``None``, empty lists and non-list payloads
    collapse to ``None`` so the renderer falls back to the
    auto-generated manifest without raising.
    """
    if not raw:
        return None
    if not isinstance(raw, (list, tuple)):
        return None
    coerced: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        coerced.append(dict(entry))
    return tuple(coerced) if coerced else None


def _apply_descriptions_override(
    publish_descriptions_by_platform: dict[str, str],
    *,
    override,
) -> None:
    """Merge the per-reel ``descriptions_override`` into the templated
    captions in-place (feature 21).

    The override is the source of truth per platform: when an agency
    user edits the caption for a single platform via
    ``PATCH .../descriptions`` the next render+publish pass must use
    that text instead of the template-derived caption. The merge is
    intentionally per-platform so a partial override (e.g. only
    Instagram) leaves the other platforms on their templated text.

    Defensive rules:
      * a missing/empty ``override`` mapping is a no-op;
      * per-platform ``None``, empty strings or whitespace-only values
        are skipped — they never wipe out the templated caption;
      * platform names are kept verbatim (the PATCH endpoint already
        validated them against ``agency_reel_defaults.platforms``).
    """
    if not override:
        return
    for platform, override_text in dict(override).items():
        if override_text is None:
            continue
        text_value = str(override_text)
        if not text_value.strip():
            continue
        publish_descriptions_by_platform[str(platform)] = text_value


__all__ = ["IngestPropertyIntoReelUseCase"]
