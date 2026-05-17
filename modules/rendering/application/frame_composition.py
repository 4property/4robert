"""Pure frame composition for property reels (step 3 of the legacy pipeline).

Orchestrates the low-level rendering primitives in
``services.media.reel_rendering.*`` (and indirectly the modern
``modules.rendering.infrastructure.*`` runtime) to produce a
``RenderedMediaArtifact`` for a ``PropertyContext`` plus prepared
``PreparedMediaAssets``. No DB access, no HTTP, no outbox: pure compute
plus filesystem writes inside a per-reel staging directory.

Replaces the body of ``DefaultMediaRenderer`` from the now-deleted
``application/pipeline/media_services.py``. The bridge
``application/bootstrap/pipeline_adapters`` keeps the four thin
adapters (``DefaultPropertyInfoService``, ``DefaultMediaPreparationService``,
``FileSystemMediaPublisher``, ``CompositeMediaPublisher``); the renderer
moved here because it is the only piece of pure compute left and it
belongs to the rendering bounded context.

The class name ``DefaultMediaRenderer`` is preserved verbatim to satisfy
the legacy ``MediaRenderer`` Protocol in
``application/pipeline/interfaces.py`` without forcing changes to
``application/pipeline/media_pipeline.py``. Feature 16 retires the
class entirely when it replaces ``PropertyMediaPipeline``.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from uuid import uuid4

from modules.reels.domain.types import (
    PreparedMediaAssets,
    PropertyContext,
    RenderedMediaArtifact,
)
from shared.observability import format_console_block, format_detail_line
from modules.rendering.infrastructure.ffmpeg import (
    build_reel_template_for_render_profile,
    generate_property_reel_from_data,
)
from modules.rendering.infrastructure.ffmpeg.intro_concat import concat_intro_to_reel
from modules.rendering.infrastructure.ffmpeg.outro_concat import concat_outro_to_reel
from modules.rendering.infrastructure.manifest import write_property_reel_manifest_from_data
from modules.rendering.infrastructure.models import PropertyRenderData, SubtitleStyle
from modules.rendering.infrastructure.poster import generate_property_poster_from_data
from modules.rendering.infrastructure.preparation import prepare_reel_render_assets
from modules.rendering.infrastructure.render_template_settings import (
    build_property_reel_template_from_overrides,
)
from modules.rendering.infrastructure.runtime import (
    build_local_selected_slides,
    resolve_ffmpeg_binary,
)

logger = logging.getLogger(__name__)


class DefaultMediaRenderer:
    def __init__(self, workspace_dir: str | Path) -> None:
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()

    def render_media(
        self,
        context: PropertyContext,
        prepared_assets: PreparedMediaAssets,
    ) -> RenderedMediaArtifact:
        return self._render_reel(context, prepared_assets)

    def render_video(
        self,
        context: PropertyContext,
        selected_photos: PreparedMediaAssets,
    ) -> RenderedMediaArtifact:
        return self.render_media(context, selected_photos)

    def _render_reel(
        self,
        context: PropertyContext,
        prepared_assets: PreparedMediaAssets,
    ) -> RenderedMediaArtifact:
        revision_id = uuid4().hex
        reel_base_template = build_property_reel_template_from_overrides(
            context.render_template_reel_settings
        )
        poster_template = build_property_reel_template_from_overrides(
            context.render_template_poster_settings
        )
        template = build_reel_template_for_render_profile(
            context.delivery_plan.render_profile,
            template=reel_base_template,
        )
        staging_root = context.storage_paths.generated_reels_root / "_staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(
            tempfile.mkdtemp(prefix=f"{context.property.slug}-", dir=staging_root)
        )
        manifest_path = staging_dir / f"{context.property.slug}-reel.json"
        media_path = staging_dir / f"{context.property.slug}-reel.mp4"
        poster_path = staging_dir / f"{context.property.slug}-poster.jpg"
        # Feature 35: when the reel carries a per-reel photo override
        # (``context.photos_override``), reorder / filter the prepared
        # photo set before the slides are built so every downstream
        # consumer (slide builder, manifest, ffmpeg pipeline) sees the
        # edited order. ``None`` (the common case) leaves the prepared
        # tuple untouched, preserving the historical render.
        prepared_assets = _apply_photos_override(
            prepared_assets, override=context.photos_override
        )
        # Feature 37: when the reel carries a per-reel slide manifest
        # override (``context.manifest_override``), drive the photo
        # array from the override's ``photo``-kind entries (sorted by
        # ``position`` so the array order matches the slide order). The
        # validator guarantees positions cover ``[0, N)`` exactly once
        # with unique ``slide_id``s; non-photo kinds (voiceover, text,
        # intro_card, outro_card) are persisted for the editor and the
        # FE preview, but do not contribute to the photo array
        # consumed by the ffmpeg pipeline today. Wraps the
        # auto-generated slide list at the same call site as feature
        # 35, so the rest of the pipeline (manifest builder, ffmpeg
        # render, poster) sees a single canonical
        # ``prepared_assets.selected_photo_paths`` tuple.
        prepared_assets = _apply_manifest_override(
            prepared_assets, override=context.manifest_override
        )
        selected_slides = build_local_selected_slides(
            prepared_assets.selected_dir,
            prepared_assets.selected_photo_paths,
        )
        property_render_data = self._build_render_data(
            context=context,
            prepared_assets=prepared_assets,
            selected_slides=selected_slides,
        )
        render_working_dir = staging_dir / "_prepared"
        layout_variant = context.render_template_layout_variant or "classic"
        # Feature 23: forward the agency-scoped background audio pool
        # resolved upstream by the ingest use case. ``None`` would make
        # the runtime fall back to ``assets/music/`` (legacy path); an
        # empty tuple is treated the same by ``resolve_background_audio_paths``.
        prepared_music_tracks = (
            context.background_audio_candidates
            if context.background_audio_candidates
            else None
        )
        prepared_render_assets = prepare_reel_render_assets(
            self.workspace_dir,
            property_render_data,
            template=template,
            working_dir=render_working_dir,
            layout_variant=layout_variant,
            music_tracks=prepared_music_tracks,
        )

        write_property_reel_manifest_from_data(
            self.workspace_dir,
            property_render_data,
            output_path=manifest_path,
            template=template,
            render_profile=context.delivery_plan.render_profile,
            render_template_id=context.render_template_id,
            render_template_settings_hash=context.render_template_settings_hash,
            poster_template=poster_template,
            prepared_assets=prepared_render_assets,
            working_dir=render_working_dir,
        )
        generate_property_reel_from_data(
            self.workspace_dir,
            property_render_data,
            output_path=media_path,
            template=template,
            prepared_assets=prepared_render_assets,
            working_dir=render_working_dir,
            layout_variant=layout_variant,
        )
        # Feature 34: when the agency has uploaded an intro and toggled
        # intro_enabled, prepend it at the start of the rendered reel.
        # Runs BEFORE the outro concat so the final order is always
        # ``intro + base_reel + outro`` when both are present. Both
        # passes mutate ``media_path`` in place.
        if (
            context.intro_source == "uploaded"
            and context.intro_local_path is not None
        ):
            _prepend_intro_to_reel(
                reel_path=media_path,
                intro_path=context.intro_local_path,
                template=template,
            )
        # Feature 33: when the agency has uploaded an outro and toggled
        # outro_enabled, concatenate it at the end of the rendered reel.
        # The concat re-encodes the outro to match the reel's geometry /
        # audio shape before invoking ffmpeg's concat demuxer (see
        # ``concat_outro_to_reel`` for the trade-offs).
        if (
            context.outro_source == "uploaded"
            and context.outro_local_path is not None
        ):
            _append_outro_to_reel(
                reel_path=media_path,
                outro_path=context.outro_local_path,
                template=template,
            )
        generate_property_poster_from_data(
            self.workspace_dir,
            property_render_data,
            output_path=poster_path,
            template=poster_template,
            layout_variant=layout_variant,
        )
        logger.info(
            format_console_block(
                "Reel Render Completed",
                format_detail_line("Site ID", context.site_id),
                format_detail_line("Property ID", context.property.id),
                format_detail_line("Render profile", context.delivery_plan.render_profile),
                format_detail_line("Revision ID", revision_id),
                format_detail_line("Staging directory", staging_dir),
                format_detail_line("Manifest path", manifest_path),
                format_detail_line("Media path", media_path),
                format_detail_line("Poster path", poster_path),
            )
        )
        return RenderedMediaArtifact(
            staging_dir=staging_dir,
            artifact_kind="reel_video",
            media_path=media_path,
            metadata_path=manifest_path,
            revision_id=revision_id,
        )

    @staticmethod
    def _build_render_data(
        *,
        context: PropertyContext,
        prepared_assets: PreparedMediaAssets,
        selected_slides,
    ) -> PropertyRenderData:
        # Hotfix 2026-05-15: side_banner colours come exclusively from
        # the agency brand row now. Feature 16 used to thread the
        # per-property WordPress webhook accent (``wppd_accent_*``) here
        # and the brand colour was only a fallback (via the
        # ``fallback_accent_*_color`` keys stashed during ingestion).
        # The product decision is to stop consulting the webhook feed at
        # this layer: ``BrandSettings.primary_color`` →
        # ``side_banner_panel_color`` (see below) drives the top /
        # bottom panels, and ``BrandSettings.secondary_color`` →
        # ``side_banner_ribbon_background_color`` drives the ribbon.
        # ``accent_text_color`` / ``accent_background_color`` are kept
        # on the dataclass for backwards compatibility with consumers
        # that still read them, but they are never populated by this
        # builder. Defaults inside ``filters.py`` /
        # ``preparation.py`` take over when no brand value is supplied.
        reel_settings = context.render_template_reel_settings or {}
        accent_text_color: str | None = None
        accent_background_color: str | None = None
        # Feature 29: the agency brand secondary color flows through
        # ``render_template_reel_settings`` as the renderer-internal
        # ``side_banner_ribbon_background_color`` key (set in
        # ``ingest_property_into_reel`` from
        # ``BrandSettings.secondary_color``). ``None`` lets the
        # preparation step fall back to the hardcoded ``#FECF4D`` ribbon
        # background. The classic layout never consults this field —
        # the rotated banner asset is only built for ``layout_variant
        # == "side_banner"``.
        ribbon_background_color = (
            reel_settings.get("side_banner_ribbon_background_color")
            if isinstance(reel_settings, dict)
            else None
        )
        side_banner_ribbon_background_color = (
            str(ribbon_background_color) if ribbon_background_color else None
        )
        # Hotfix 2026-05-15: ``BrandSettings.primary_color`` flows through
        # both ``reel_settings`` and ``poster_settings`` as the
        # renderer-internal ``side_banner_panel_color`` key (set in
        # ``ingest_property_into_reel``). The top / bottom panel renderer
        # in ``poster.py`` and ``render_reel.py`` uses this value as the
        # canonical colour for the side_banner header / footer, falling
        # back to ``accent_background_color`` (the per-property webhook
        # accent) and finally to ``black@0.38`` / ``black@0.46`` if both
        # are absent. Classic layout never consults this field.
        panel_color_raw = (
            reel_settings.get("side_banner_panel_color")
            if isinstance(reel_settings, dict)
            else None
        )
        side_banner_panel_color = (
            str(panel_color_raw) if panel_color_raw else None
        )
        subtitle_style = _build_subtitle_style(
            reel_settings if isinstance(reel_settings, dict) else {}
        )
        return PropertyRenderData(
            site_id=context.site_id,
            property_id=context.property.id,
            slug=context.property.slug,
            title=context.property.title or context.property.slug,
            link=context.property.link,
            property_status=context.property.property_status,
            listing_lifecycle=context.delivery_plan.listing_lifecycle,
            banner_text=context.delivery_plan.banner_text,
            selected_image_dir=prepared_assets.selected_dir,
            selected_image_paths=prepared_assets.selected_photo_paths,
            featured_image_url=context.property.featured_image_url,
            bedrooms=context.property.bedrooms,
            bathrooms=context.property.bathrooms,
            ber_rating=context.property.ber_rating,
            agent_name=context.property.agent_name,
            agent_photo_url=context.property.agent_photo_url,
            agent_email=context.property.agent_email,
            agent_mobile=context.property.agent_mobile,
            agent_number=context.property.agent_number,
            agency_psra=context.property.agency_psra,
            agency_logo_url=context.property.agency_logo_url,
            agency_logo_local_path=context.agency_logo_local_path,
            price=context.property.price,
            price_display_text=context.delivery_plan.price_display_text,
            property_type_label=context.property.property_type_label,
            property_area_label=context.property.property_area_label,
            property_county_label=context.property.property_county_label,
            eircode=context.property.eircode,
            property_size=context.property.property_size,
            selected_slides=tuple(selected_slides),
            accent_text_color=accent_text_color,
            accent_background_color=accent_background_color,
            side_banner_ribbon_background_color=side_banner_ribbon_background_color,
            side_banner_panel_color=side_banner_panel_color,
            subtitle_style=subtitle_style,
            # Feature 36: forward the per-reel subtitles override (if
            # any) onto the render data so ``compose_subtitle_segments``
            # can swap the auto-generated captions for the user-edited
            # cues. ``None`` (the common case) leaves the historical
            # autoCaptions flow untouched.
            subtitles_override=context.subtitles_override,
        )


def _build_subtitle_style(reel_settings: dict) -> SubtitleStyle:
    """Materialise renderer-internal ``subtitle_*`` keys into a SubtitleStyle.

    Feature 31: the ingest use case stashes the per-agency subtitle
    settings under snake_case keys on ``render_template_reel_settings``;
    this helper turns them into the canonical ``SubtitleStyle`` instance
    that travels with ``PropertyRenderData`` to the ffmpeg filter graph.

    Missing keys fall back to the dataclass defaults so a freshly-onboarded
    agency renders the same look the codebase had before feature 31 cabled
    the wires (outline-only subtitle, bottom position, centered, no
    uppercase, 36-char wrap). The ``enabled`` flag defaults to ``True``
    because the historical contract was "always render captions".
    """

    def _opt_str(key: str) -> str | None:
        raw = reel_settings.get(key)
        if raw is None:
            return None
        text = str(raw).strip()
        return text or None

    def _opt_int(key: str, default: int) -> int:
        raw = reel_settings.get(key)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    def _opt_bool(key: str, default: bool) -> bool:
        raw = reel_settings.get(key)
        if raw is None:
            return default
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            normalized = raw.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        return bool(raw)

    return SubtitleStyle(
        enabled=_opt_bool("auto_captions_enabled", True),
        font_family=_opt_str("subtitle_font_family"),
        weight=(_opt_str("subtitle_weight") or "700"),
        color=(_opt_str("subtitle_color") or "#ffffff"),
        bg_style=((_opt_str("subtitle_bg_style") or "outline").lower()),
        bg_color=(_opt_str("subtitle_bg_color") or "#0f1729"),
        bg_opacity=_opt_int("subtitle_bg_opacity", 82),
        position=((_opt_str("subtitle_position") or "bottom").lower()),
        alignment=((_opt_str("subtitle_alignment") or "center").lower()),
        uppercase=_opt_bool("subtitle_uppercase", False),
        max_chars=_opt_int("subtitle_max_chars", 36),
    )


def _apply_photos_override(
    prepared_assets: PreparedMediaAssets,
    *,
    override: tuple[tuple[int, bool], ...] | None,
) -> PreparedMediaAssets:
    """Reorder / filter ``prepared_assets.selected_photo_paths`` from a
    per-reel photos override (feature 35).

    ``override`` is an ordered tuple of ``(position, selected)`` pairs
    where ``position`` is the 0-indexed slot in the **prepared** photo
    set. The function:

    * returns the input unchanged when ``override`` is ``None`` or
      empty (the common case);
    * returns the input unchanged when ``selected_photo_paths`` is
      empty (nothing to reorder);
    * builds a new tuple of paths by taking each entry's ``position``
      in array order, skipping entries whose ``selected=false`` or
      whose position is out of range. Out-of-range positions are
      logged at warning level but never raise — the override layer is
      purely editorial and a stale value (e.g. positions still
      referring to a prior catalog snapshot) must not crash the
      render pipeline.

    The fallback contract matches the leader's brief: when every entry
    is out-of-range or unselected, the function returns the input
    unchanged so the renderer keeps producing a video.
    """
    if not override:
        return prepared_assets
    original_paths = tuple(prepared_assets.selected_photo_paths)
    if not original_paths:
        return prepared_assets
    reordered: list[Path] = []
    for position, selected in override:
        if not selected:
            continue
        if position < 0 or position >= len(original_paths):
            logger.warning(
                "photos_override position %s is out of range for "
                "prepared photo set of size %s; skipping entry.",
                position,
                len(original_paths),
            )
            continue
        reordered.append(original_paths[position])
    if not reordered:
        logger.warning(
            "photos_override produced no renderable photos for the "
            "prepared set; falling back to the default order."
        )
        return prepared_assets
    return PreparedMediaAssets(
        selected_dir=prepared_assets.selected_dir,
        selected_photo_paths=tuple(reordered),
        downloaded_images=prepared_assets.downloaded_images,
        primary_image_path=prepared_assets.primary_image_path,
    )


def _apply_manifest_override(
    prepared_assets: PreparedMediaAssets,
    *,
    override: tuple[dict, ...] | None,
) -> PreparedMediaAssets:
    """Reorder ``prepared_assets.selected_photo_paths`` from a per-reel
    slide manifest override (feature 37).

    ``override`` is a validated tuple of slide dicts (already
    discriminated at the PATCH layer). The function:

    * returns the input unchanged when ``override`` is ``None`` or
      empty (the common case);
    * returns the input unchanged when ``selected_photo_paths`` is
      empty (nothing to reorder);
    * filters the override down to ``kind == "photo"`` entries (only
      those map to actual image slides today; the other kinds are
      persisted for the FE editor preview), sorts them by ``position``
      so the array order matches the slide order in the rendered
      reel, then rebuilds the path tuple by taking each entry's
      ``photo_position`` from the prepared photo set. Out-of-range
      ``photo_position`` values are logged at warning level but never
      raise — the override layer is purely editorial and a stale value
      must not crash the render pipeline.

    The fallback contract matches the per-feature decisions for
    features 35 / 36: when every photo-kind entry is out of range (or
    there are no photo-kind entries at all), the function returns the
    input unchanged so the renderer keeps producing a non-empty video.
    """
    if not override:
        return prepared_assets
    original_paths = tuple(prepared_assets.selected_photo_paths)
    if not original_paths:
        return prepared_assets
    photo_entries = [
        entry for entry in override
        if isinstance(entry, dict) and entry.get("kind") == "photo"
    ]
    if not photo_entries:
        return prepared_assets
    photo_entries.sort(key=lambda entry: int(entry.get("position", 0)))
    reordered: list[Path] = []
    for entry in photo_entries:
        try:
            photo_position = int(entry.get("photo_position"))
        except (TypeError, ValueError):
            logger.warning(
                "manifest_override slide_id=%s has invalid "
                "photo_position; skipping entry.",
                entry.get("slide_id"),
            )
            continue
        if photo_position < 0 or photo_position >= len(original_paths):
            logger.warning(
                "manifest_override photo_position %s is out of range "
                "for prepared photo set of size %s; skipping entry.",
                photo_position,
                len(original_paths),
            )
            continue
        reordered.append(original_paths[photo_position])
    if not reordered:
        logger.warning(
            "manifest_override produced no renderable photos for the "
            "prepared set; falling back to the default order."
        )
        return prepared_assets
    return PreparedMediaAssets(
        selected_dir=prepared_assets.selected_dir,
        selected_photo_paths=tuple(reordered),
        downloaded_images=prepared_assets.downloaded_images,
        primary_image_path=prepared_assets.primary_image_path,
    )


def _append_outro_to_reel(
    *,
    reel_path: Path,
    outro_path: Path,
    template,
) -> None:
    """Concatenate ``outro_path`` after ``reel_path`` in place.

    Writes the combined output to a sibling ``*.with_outro.mp4`` file
    and atomically replaces the original reel on success. On failure
    the original reel is preserved untouched and the error bubbles up;
    callers higher in the pipeline are responsible for deciding whether
    to fail the job or proceed with the un-concatenated reel.
    """
    ffmpeg_binary = resolve_ffmpeg_binary()
    combined_path = reel_path.with_suffix(".with_outro.mp4")
    try:
        concat_outro_to_reel(
            ffmpeg_binary=ffmpeg_binary,
            reel_path=reel_path,
            outro_path=outro_path,
            output_path=combined_path,
            width=int(template.width),
            height=int(template.height),
            fps=int(template.fps),
        )
        combined_path.replace(reel_path)
    finally:
        # ``replace`` consumed ``combined_path`` on success; clean up
        # the leftover only if the rename never happened.
        if combined_path.exists():
            try:
                combined_path.unlink()
            except OSError:  # pragma: no cover — defensive
                logger.exception(
                    "Failed to clean up leftover outro-concat path %s",
                    combined_path,
                )


def _prepend_intro_to_reel(
    *,
    reel_path: Path,
    intro_path: Path,
    template,
) -> None:
    """Concatenate ``intro_path`` before ``reel_path`` in place.

    Feature 34: symmetric to :func:`_append_outro_to_reel`. Writes the
    combined output to a sibling ``*.with_intro.mp4`` and atomically
    replaces the original reel on success. On failure the original reel
    is preserved untouched and the error bubbles up.
    """
    ffmpeg_binary = resolve_ffmpeg_binary()
    combined_path = reel_path.with_suffix(".with_intro.mp4")
    try:
        concat_intro_to_reel(
            ffmpeg_binary=ffmpeg_binary,
            reel_path=reel_path,
            intro_path=intro_path,
            output_path=combined_path,
            width=int(template.width),
            height=int(template.height),
            fps=int(template.fps),
        )
        combined_path.replace(reel_path)
    finally:
        if combined_path.exists():
            try:
                combined_path.unlink()
            except OSError:  # pragma: no cover — defensive
                logger.exception(
                    "Failed to clean up leftover intro-concat path %s",
                    combined_path,
                )


__all__ = ["DefaultMediaRenderer"]
