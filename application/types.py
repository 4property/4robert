from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from models.property import Property
from repositories.property_pipeline_repository import DownloadedImage
from services.webhook_transport.site_storage import SiteStorageLayout


def _normalise_platforms(raw_platforms: list[object] | tuple[object, ...]) -> tuple[str, ...]:
    normalized_platforms: list[str] = []
    seen: set[str] = set()
    for raw_platform in raw_platforms:
        platform = str(raw_platform or "").strip().lower()
        if not platform or platform in seen:
            continue
        seen.add(platform)
        normalized_platforms.append(platform)
    return tuple(normalized_platforms)


@dataclass(frozen=True, slots=True)
class SocialPublishContext:
    provider: str
    location_id: str
    access_token: str
    platforms: tuple[str, ...]

    def to_dict(self, *, include_access_token: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "provider": self.provider,
            "location_id": self.location_id,
            "platforms": list(self.platforms),
        }
        if include_access_token:
            payload["access_token"] = self.access_token
        return payload

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
        return cls(
            provider=provider,
            location_id=location_id,
            access_token=access_token,
            platforms=platforms,
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
class PropertyVideoJob:
    event_id: str
    site_id: str
    property_id: int | None
    received_at: str
    raw_payload_hash: str
    payload: dict[str, Any]
    publish_context: SocialPublishContext | None = None
    job_id: str = ""


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
    site_id: str
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
    def requires_photo_selection(self) -> bool:
        return self.requires_asset_preparation

    @property
    def existing_published_video(self) -> PublishedMediaArtifact | None:
        return self.existing_published_media


def _guess_mime_type(artifact_kind: str, media_path: Path) -> str:
    guessed_mime_type = mimetypes.guess_type(media_path.name)[0]
    if guessed_mime_type:
        return guessed_mime_type
    if artifact_kind == "reel_video":
        return "video/mp4"
    if artifact_kind == "poster_image":
        return "image/jpeg"
    return "application/octet-stream"


PublishedVideoArtifact = PublishedMediaArtifact
PropertyMediaJob = PropertyVideoJob
RenderedVideoArtifact = RenderedMediaArtifact
SelectedPhotoSet = PreparedMediaAssets


__all__ = [
    "MediaDeliveryPlan",
    "PreparedMediaAssets",
    "PropertyContext",
    "PropertyMediaJob",
    "PropertyVideoJob",
    "PublishedMediaArtifact",
    "PublishedVideoArtifact",
    "RenderedMediaArtifact",
    "RenderedVideoArtifact",
    "SelectedPhotoSet",
    "SocialPublishContext",
]
