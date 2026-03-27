from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from models.property import Property
from repositories.property_pipeline_repository import DownloadedImage
from services.webhook_transport.site_storage import SiteStorageLayout


@dataclass(frozen=True, slots=True)
class SocialPublishContext:
    provider: str
    location_id: str
    access_token: str
    platform: str

    def to_dict(self, *, include_access_token: bool = True) -> dict[str, str]:
        payload = {
            "provider": self.provider,
            "location_id": self.location_id,
            "platform": self.platform,
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
        platform = str(payload.get("platform") or "").strip()
        access_token = str(payload.get("access_token") or "").strip()
        if not provider or not location_id or not platform:
            return None
        return cls(
            provider=provider,
            location_id=location_id,
            access_token=access_token,
            platform=platform,
        )


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


@dataclass(frozen=True, slots=True)
class PublishedVideoArtifact:
    manifest_path: Path
    video_path: Path


@dataclass(frozen=True, slots=True)
class PropertyContext:
    workspace_dir: Path
    storage_paths: SiteStorageLayout
    site_id: str
    property: Property
    publish_context: SocialPublishContext | None = None
    publish_description: str | None = None
    publish_target_url: str | None = None
    content_fingerprint: str = ""
    content_snapshot_json: str = ""
    publish_target_fingerprint: str = ""
    publish_target_snapshot_json: str = ""
    requires_photo_selection: bool = True
    requires_render: bool = True
    requires_external_publish: bool = True
    existing_published_video: PublishedVideoArtifact | None = None
    is_noop: bool = False


@dataclass(frozen=True, slots=True)
class SelectedPhotoSet:
    selected_dir: Path
    selected_photo_paths: tuple[Path, ...]
    downloaded_images: tuple[DownloadedImage, ...]


@dataclass(frozen=True, slots=True)
class RenderedVideoArtifact:
    staging_dir: Path
    manifest_path: Path
    video_path: Path


__all__ = [
    "PropertyContext",
    "PropertyVideoJob",
    "PublishedVideoArtifact",
    "RenderedVideoArtifact",
    "SelectedPhotoSet",
    "SocialPublishContext",
]

