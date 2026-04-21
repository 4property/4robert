from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from domain.properties.model import Property
from domain.publishing.types import PlatformPublishTargetPlan, SocialPublishContext
from domain.tenancy.context import TenantContext
from domain.tenancy.storage import SiteStorageLayout

DownloadedImage = tuple[int, str, Path | None]


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
    pending_publish_platforms: tuple[str, ...] = field(default_factory=tuple)
    requires_asset_preparation: bool = True
    requires_render: bool = True
    requires_external_publish: bool = True
    existing_published_media: PublishedMediaArtifact | None = None
    is_noop: bool = False

    @property
    def site_id(self) -> str:
        return self.tenant.site_id

    @property
    def requires_photo_selection(self) -> bool:
        return self.requires_asset_preparation


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
    "MediaDeliveryPlan",
    "PreparedMediaAssets",
    "PropertyContext",
    "PropertyMediaJob",
    "PublishedMediaArtifact",
    "RenderedMediaArtifact",
]
