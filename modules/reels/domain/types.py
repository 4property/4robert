"""Reels domain types: media job, contexts, artifacts, publish plan.

Moved from ``application/types.py`` during sub-feature 18b. The ``Property``
aggregate referenced by ``PropertyContext`` lives in
``modules.catalog.domain.wordpress_property``; ``TenantContext`` and
``SiteStorageLayout`` live in ``modules.tenancy.domain``. ``DownloadedImage``
is co-located here because the only consumer (``PreparedMediaAssets``) is in
this module.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from modules.catalog.domain.wordpress_property import Property
from modules.tenancy.domain.context import TenantContext
from modules.tenancy.domain.storage import SiteStorageLayout


DownloadedImage = tuple[int, str, Path | None]


_PLATFORM_ALIASES = {
    "google business profile": "google_business_profile",
    "google-business-profile": "google_business_profile",
    "google_business_profile": "google_business_profile",
    "gbp": "google_business_profile",
}


def _normalize_platform_name(platform: str) -> str:
    normalized_platform = str(platform or "").strip().lower()
    return _PLATFORM_ALIASES.get(normalized_platform, normalized_platform)


def _normalise_platforms(raw_platforms: list[object] | tuple[object, ...]) -> tuple[str, ...]:
    normalized_platforms: list[str] = []
    seen: set[str] = set()
    for raw_platform in raw_platforms:
        platform = _normalize_platform_name(str(raw_platform or ""))
        if not platform or platform in seen:
            continue
        seen.add(platform)
        normalized_platforms.append(platform)
    return tuple(normalized_platforms)


def _iter_pairs(raw: Any) -> list[tuple[Any, Any]]:
    """Yield ``(key, value)`` pairs from either a dict or a sequence of pairs.

    Returns an empty list for anything that is not iterable as pairs. Used to
    parse template/hashtag payloads that may have been serialised as either
    shape over the wire.
    """
    if raw is None:
        return []
    if isinstance(raw, dict):
        return list(raw.items())
    if isinstance(raw, (list, tuple)):
        pairs: list[tuple[Any, Any]] = []
        for entry in raw:
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                pairs.append((entry[0], entry[1]))
        return pairs
    return []


def _normalise_template_pairs(raw: Any) -> tuple[tuple[str, str], ...]:
    """Normalise a `platform -> template_string` mapping from either shape."""
    return tuple(
        (str(key).strip().lower(), str(value))
        for key, value in _iter_pairs(raw)
        if str(key).strip()
    )


def _normalise_hashtag_pairs(raw: Any) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Normalise a `platform -> list[hashtag]` mapping from either shape."""
    return tuple(
        (
            str(key).strip().lower(),
            tuple(
                str(tag).strip()
                for tag in (value if isinstance(value, (list, tuple)) else ())
                if str(tag).strip()
            ),
        )
        for key, value in _iter_pairs(raw)
        if str(key).strip()
    )


@dataclass(frozen=True, slots=True)
class SocialPublishContext:
    provider: str
    location_id: str
    access_token: str
    platforms: tuple[str, ...]
    approval_required: bool = False
    social_templates: tuple[tuple[str, str], ...] = ()
    social_title_templates: tuple[tuple[str, str], ...] = ()
    social_hashtags: tuple[tuple[str, tuple[str, ...]], ...] = ()
    scheduled_at: str | None = None
    render_template_id: str = "classic"
    # Feature 25: per-reel music override forwarded by the
    # ``UpdateReelMusicOverrideUseCase``. ``None`` means "no override —
    # fall back to the agency pool resolver" (features 23 / 24). When
    # set, the ingest step swaps the resolved pool for a single-element
    # tuple containing just this track. Jobs enqueued before feature 25
    # never carry the field, which round-trips to ``None`` and preserves
    # the legacy behaviour.
    override_music_track_id: str | None = None

    def to_dict(self, *, include_access_token: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "provider": self.provider,
            "location_id": self.location_id,
            "platforms": list(self.platforms),
            "approval_required": self.approval_required,
            "social_templates": dict(self.social_templates),
            "social_title_templates": dict(self.social_title_templates),
            "social_hashtags": {
                platform: list(tags) for platform, tags in self.social_hashtags
            },
            "scheduled_at": self.scheduled_at,
            "render_template_id": self.render_template_id,
            "override_music_track_id": self.override_music_track_id,
        }
        if include_access_token:
            payload["access_token"] = self.access_token
        return payload

    @property
    def social_templates_map(self) -> dict[str, str]:
        return dict(self.social_templates)

    @property
    def social_title_templates_map(self) -> dict[str, str]:
        return dict(self.social_title_templates)

    @property
    def social_hashtags_map(self) -> dict[str, tuple[str, ...]]:
        return {platform: tags for platform, tags in self.social_hashtags}

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "SocialPublishContext | None":
        if not payload:
            return None
        provider = str(payload.get("provider") or "").strip()
        location_id = str(payload.get("location_id") or "").strip()
        access_token = str(payload.get("access_token") or "").strip()
        raw_platforms = payload.get("platforms")
        platforms: tuple[str, ...]
        if isinstance(raw_platforms, (list, tuple)):
            platforms = _normalise_platforms(tuple(raw_platforms))
        elif raw_platforms is not None:
            platforms = _normalise_platforms((raw_platforms,))
        else:
            platforms = _normalise_platforms((payload.get("platform"),))
        if not provider or not location_id or not platforms:
            return None
        approval_required = bool(payload.get("approval_required", False))
        # `social_templates` / `social_title_templates` may travel as a dict
        # (canonical shape produced by `to_dict`) OR as a list of
        # ``[platform, value]`` pairs (legacy shape produced by the webhook
        # ingest use case, which serialises a ``tuple[tuple[str,str], ...]``
        # to JSON and round-trips through Postgres as ``list[list[str]]``).
        # Accept both so a job enqueued before this fix is honoured.
        normalized_templates = _normalise_template_pairs(
            payload.get("social_templates")
        )
        normalized_title_templates = _normalise_template_pairs(
            payload.get("social_title_templates")
        )
        normalized_hashtags = _normalise_hashtag_pairs(
            payload.get("social_hashtags")
        )
        raw_scheduled_at = payload.get("scheduled_at")
        if raw_scheduled_at is None:
            scheduled_at: str | None = None
        else:
            normalized_scheduled_at = str(raw_scheduled_at).strip()
            scheduled_at = normalized_scheduled_at or None
        render_template_id = str(payload.get("render_template_id") or "").strip()
        # Feature 25: pre-feature-25 jobs do not carry the key, so
        # ``dict.get(...)`` returns ``None`` and the override is treated
        # as absent (backward-compat).
        raw_override_music_track_id = payload.get("override_music_track_id")
        if raw_override_music_track_id is None:
            override_music_track_id: str | None = None
        else:
            normalized_override = str(raw_override_music_track_id).strip()
            override_music_track_id = normalized_override or None
        return cls(
            provider=provider,
            location_id=location_id,
            access_token=access_token,
            platforms=platforms,
            approval_required=approval_required,
            social_templates=normalized_templates,
            social_title_templates=normalized_title_templates,
            social_hashtags=normalized_hashtags,
            scheduled_at=scheduled_at,
            render_template_id=render_template_id or "classic",
            override_music_track_id=override_music_track_id,
        )


@dataclass(frozen=True, slots=True)
class MediaDeliveryPlan:
    listing_lifecycle: str
    artifact_kind: str
    render_profile: str
    social_post_type: str
    asset_strategy: str
    banner_text: str | None = None
    price_display_text: str | None = None

    @property
    def uses_primary_image_only(self) -> bool:
        return self.asset_strategy == "primary_only"


@dataclass(frozen=True, slots=True)
class PlatformPublishTargetPlan:
    platform: str
    artifact_kind: str
    social_post_type: str
    description: str
    title: str | None = None
    target_url: str | None = None


@dataclass(frozen=True, slots=True)
class PropertyMediaJob:
    event_id: str
    tenant: TenantContext
    property_id: int | None
    received_at: str
    raw_payload_hash: str
    payload: dict[str, Any]
    publish_context: SocialPublishContext | None = None
    job_id: str = ""

    @property
    def site_id(self) -> str:
        return self.tenant.site_id


@dataclass(frozen=True, slots=True, init=False)
class PublishedMediaArtifact:
    artifact_kind: str
    media_path: Path
    metadata_path: Path | None
    mime_type: str
    revision_id: str

    def __init__(
        self,
        *,
        artifact_kind: str = "reel_video",
        media_path: Path | None = None,
        metadata_path: Path | None = None,
        mime_type: str | None = None,
        revision_id: str = "",
        manifest_path: Path | None = None,
        video_path: Path | None = None,
    ) -> None:
        resolved_source = media_path or video_path
        if resolved_source is None:
            raise TypeError("PublishedMediaArtifact requires a media_path.")
        resolved_media_path = Path(resolved_source)

        resolved_metadata_path = metadata_path or manifest_path
        resolved_mime_type = mime_type or _guess_mime_type(artifact_kind, resolved_media_path)

        object.__setattr__(self, "artifact_kind", artifact_kind)
        object.__setattr__(self, "media_path", resolved_media_path)
        object.__setattr__(self, "metadata_path", resolved_metadata_path)
        object.__setattr__(self, "mime_type", resolved_mime_type)
        object.__setattr__(self, "revision_id", str(revision_id or ""))

    @property
    def manifest_path(self) -> Path | None:
        return self.metadata_path

    @property
    def video_path(self) -> Path:
        return self.media_path


@dataclass(frozen=True, slots=True)
class PreparedMediaAssets:
    selected_dir: Path
    selected_photo_paths: tuple[Path, ...]
    downloaded_images: tuple[DownloadedImage, ...]
    primary_image_path: Path | None = None


@dataclass(frozen=True, slots=True, init=False)
class RenderedMediaArtifact:
    staging_dir: Path
    artifact_kind: str
    media_path: Path
    metadata_path: Path | None
    mime_type: str
    revision_id: str

    def __init__(
        self,
        *,
        staging_dir: Path,
        artifact_kind: str = "reel_video",
        media_path: Path | None = None,
        metadata_path: Path | None = None,
        mime_type: str | None = None,
        revision_id: str = "",
        manifest_path: Path | None = None,
        video_path: Path | None = None,
    ) -> None:
        resolved_source = media_path or video_path
        if resolved_source is None:
            raise TypeError("RenderedMediaArtifact requires a media_path.")
        resolved_media_path = Path(resolved_source)

        resolved_metadata_path = metadata_path or manifest_path
        resolved_mime_type = mime_type or _guess_mime_type(artifact_kind, resolved_media_path)

        object.__setattr__(self, "staging_dir", staging_dir)
        object.__setattr__(self, "artifact_kind", artifact_kind)
        object.__setattr__(self, "media_path", resolved_media_path)
        object.__setattr__(self, "metadata_path", resolved_metadata_path)
        object.__setattr__(self, "mime_type", resolved_mime_type)
        object.__setattr__(self, "revision_id", str(revision_id or ""))

    @property
    def manifest_path(self) -> Path | None:
        return self.metadata_path

    @property
    def video_path(self) -> Path:
        return self.media_path


@dataclass(frozen=True, slots=True)
class PropertyContext:
    workspace_dir: Path
    storage_paths: SiteStorageLayout
    tenant: TenantContext
    property: Property
    delivery_plan: MediaDeliveryPlan = field(
        default_factory=lambda: MediaDeliveryPlan(
            listing_lifecycle="for_sale",
            artifact_kind="reel_video",
            render_profile="for_sale_reel",
            social_post_type="reel",
            asset_strategy="curated_selection",
            banner_text="FOR SALE",
            price_display_text=None,
        )
    )
    publish_context: SocialPublishContext | None = None
    publish_descriptions_by_platform: dict[str, str] = field(default_factory=dict)
    publish_titles_by_platform: dict[str, str] = field(default_factory=dict)
    publish_targets: tuple[PlatformPublishTargetPlan, ...] = field(default_factory=tuple)
    publish_target_url: str | None = None
    content_fingerprint: str = ""
    content_snapshot_json: str = ""
    publish_target_fingerprint: str = ""
    publish_target_snapshot_json: str = ""
    render_template_id: str = "classic"
    render_template_settings_hash: str = ""
    render_template_layout_variant: str = "classic"
    render_template_reel_settings: dict[str, object] = field(default_factory=dict)
    render_template_poster_settings: dict[str, object] = field(default_factory=dict)
    pending_publish_platforms: tuple[str, ...] = field(default_factory=tuple)
    requires_asset_preparation: bool = True
    requires_render: bool = True
    requires_external_publish: bool = True
    existing_published_media: PublishedMediaArtifact | None = None
    is_noop: bool = False
    agency_logo_local_path: Path | None = None
    background_audio_candidates: tuple[Path, ...] = field(default_factory=tuple)
    # Feature 33: when the agency has uploaded an outro
    # (``agency_intro_outro_assets.source='uploaded'``) and toggled
    # ``agency_reel_defaults.outro_enabled``, the ingest use case fills
    # in the on-disk path here. The renderer concatenates this video
    # after the reel via ``concat_outro_to_reel``. ``None`` (or an
    # ``outro_source != 'uploaded'``) skips the concat — current
    # behaviour preserved.
    outro_local_path: Path | None = None
    outro_source: str = "none"
    outro_duration_seconds: int = 0
    # Feature 34: symmetric path for the per-agency intro video. When
    # ``agency_intro_outro_assets.source='uploaded'`` with ``kind='intro'``
    # AND ``agency_reel_defaults.intro_enabled=true`` AND the blob is on
    # disk, the ingest use case fills in the path here. The renderer
    # prepends this video to the reel via ``concat_intro_to_reel``. When
    # both intro and outro are present the final order is
    # ``intro + base_reel + outro``.
    intro_local_path: Path | None = None
    intro_source: str = "none"
    intro_duration_seconds: int = 0
    # Feature 35: per-reel photo override forwarded from
    # ``reels.photos_override``. ``None`` means "no override — render in
    # the default property_images order". Otherwise an ordered tuple of
    # ``(position, selected)`` pairs where ``position`` is the original
    # 0-indexed photo slot and ``selected=false`` drops the slot from
    # the rendered reel. The renderer applies this in
    # ``frame_composition._render_reel`` before constructing the
    # PropertyRenderData / manifest.
    photos_override: tuple[tuple[int, bool], ...] | None = None
    # Feature 36: per-reel subtitle override forwarded from
    # ``reels.subtitles_override``. ``None`` means "no override — fall
    # back to the autoCaptions flow (drawtext on every slide derived
    # from the slide caption text) when ``subtitle_style.enabled`` is
    # True". Otherwise an ordered tuple of
    # ``(index, text, in_seconds, out_seconds)`` cues that bypass the
    # autoCaptions composer entirely; the renderer builds the subtitle
    # drawtext directly from these cues. Validation (text length,
    # unique monotone index, no overlap, non-negative times) lives at
    # the PATCH layer so the renderer can trust the shape here.
    subtitles_override: (
        tuple[tuple[int, str, float, float], ...] | None
    ) = None
    # Feature 37: per-reel slide manifest override forwarded from
    # ``reels.manifest_override``. ``None`` means "no override — fall
    # back to the auto-generated manifest pipeline". Otherwise an
    # ordered tuple of opaque slide dicts (already validated /
    # discriminated at the PATCH layer). The renderer consumes the
    # tuple directly to drive the scene list: positions ordered, each
    # ``kind`` selects how the slide is built. The PATCH layer keeps
    # the shape canonical so the renderer can trust the entries here.
    manifest_override: tuple[dict[str, Any], ...] | None = None

    @property
    def requires_photo_selection(self) -> bool:
        return self.requires_asset_preparation

    @property
    def site_id(self) -> str:
        return self.tenant.site_id


def _guess_mime_type(artifact_kind: str, media_path: Path) -> str:
    guessed_mime_type = mimetypes.guess_type(media_path.name)[0]
    if guessed_mime_type:
        return guessed_mime_type
    if artifact_kind == "reel_video":
        return "video/mp4"
    if artifact_kind == "poster_image":
        return "image/jpeg"
    return "application/octet-stream"


__all__ = [
    "DownloadedImage",
    "MediaDeliveryPlan",
    "PlatformPublishTargetPlan",
    "PreparedMediaAssets",
    "PropertyContext",
    "PropertyMediaJob",
    "PublishedMediaArtifact",
    "RenderedMediaArtifact",
    "SocialPublishContext",
]
