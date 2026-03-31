from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class SocialAccount:
    id: str
    name: str
    platform: str
    account_type: str
    is_expired: bool
    raw_data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LocationUser:
    id: str
    first_name: str
    last_name: str
    email: str
    raw_data: dict[str, Any]

    @property
    def display_name(self) -> str:
        return " ".join(part for part in (self.first_name, self.last_name) if part).strip() or self.email or self.id


@dataclass(frozen=True, slots=True)
class UploadedMedia:
    file_id: str
    url: str
    mime_type: str
    file_name: str
    raw_response: dict[str, Any]

    @property
    def media_kind(self) -> str:
        if self.mime_type.startswith("image/"):
            return "image"
        return "video"


@dataclass(frozen=True, slots=True)
class CreatedSocialPost:
    post_id: str | None
    status: str | None
    message: str | None
    raw_response: dict[str, Any]


@dataclass(frozen=True, slots=True, init=False)
class PublishMediaRequest:
    media_path: Path
    description: str
    title: str | None
    upload_file_name: str | None
    target_url: str | None
    provider: str
    location_id: str
    access_token: str
    platform: str
    social_post_type: str
    artifact_kind: str
    account_id: str | None
    user_id: str | None
    source_site_id: str | None

    def __init__(
        self,
        *,
        media_path: Path | None = None,
        video_path: Path | None = None,
        description: str = "",
        title: str | None = None,
        upload_file_name: str | None = None,
        target_url: str | None = None,
        provider: str = "gohighlevel",
        location_id: str = "",
        access_token: str = "",
        platform: str = "tiktok",
        social_post_type: str = "reel",
        artifact_kind: str = "reel_video",
        account_id: str | None = None,
        user_id: str | None = None,
        source_site_id: str | None = None,
    ) -> None:
        resolved_media_path = media_path or video_path
        if resolved_media_path is None:
            raise TypeError("PublishMediaRequest requires a media_path.")

        object.__setattr__(self, "media_path", Path(resolved_media_path))
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "upload_file_name", upload_file_name)
        object.__setattr__(self, "target_url", target_url)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "location_id", location_id)
        object.__setattr__(self, "access_token", access_token)
        object.__setattr__(self, "platform", platform)
        object.__setattr__(self, "social_post_type", social_post_type)
        object.__setattr__(self, "artifact_kind", artifact_kind)
        object.__setattr__(self, "account_id", account_id)
        object.__setattr__(self, "user_id", user_id)
        object.__setattr__(self, "source_site_id", source_site_id)

    @property
    def video_path(self) -> Path:
        return self.media_path


@dataclass(frozen=True, slots=True)
class PublishMediaResult:
    selected_account: SocialAccount
    selected_user: LocationUser
    uploaded_media: UploadedMedia
    created_post: CreatedSocialPost
    description: str
    target_url: str | None
    source_site_id: str | None
    social_post_type: str
    artifact_kind: str


SUCCESSFUL_PLATFORM_OUTCOMES = frozenset(
    {"published", "scheduled", "queued", "processing", "created", "accepted"}
)
FAILED_PLATFORM_OUTCOMES = frozenset({"failed", "error", "rejected", "cancelled"})


@dataclass(frozen=True, slots=True)
class PlatformPublishOutcome:
    platform: str
    outcome: str
    retryable: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)
    account_id: str | None = None
    account_name: str | None = None
    user_id: str | None = None
    user_display_name: str | None = None
    post_id: str | None = None
    post_status: str | None = None
    message: str | None = None
    trace_id: str | None = None
    error: str | None = None

    @property
    def is_success(self) -> bool:
        normalized_outcome = self.outcome.strip().lower()
        normalized_post_status = (self.post_status or "").strip().lower()
        if (
            normalized_outcome in FAILED_PLATFORM_OUTCOMES
            or normalized_post_status in FAILED_PLATFORM_OUTCOMES
        ):
            return False
        return (
            normalized_outcome in SUCCESSFUL_PLATFORM_OUTCOMES
            or normalized_post_status in SUCCESSFUL_PLATFORM_OUTCOMES
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "outcome": self.outcome,
            "retryable": self.retryable,
            "warnings": list(self.warnings),
            "account_id": self.account_id,
            "account_name": self.account_name,
            "user_id": self.user_id,
            "user_display_name": self.user_display_name,
            "post_id": self.post_id,
            "post_status": self.post_status,
            "message": self.message,
            "trace_id": self.trace_id,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True, init=False)
class MultiPlatformPublishRequest:
    media_path: Path
    descriptions_by_platform: dict[str, str]
    titles_by_platform: dict[str, str]
    upload_file_name: str | None
    target_url: str | None
    provider: str
    location_id: str
    access_token: str
    platforms: tuple[str, ...]
    user_id: str | None
    source_site_id: str | None
    social_post_type: str
    artifact_kind: str

    def __init__(
        self,
        *,
        media_path: Path | None = None,
        video_path: Path | None = None,
        descriptions_by_platform: dict[str, str] | None = None,
        titles_by_platform: dict[str, str] | None = None,
        upload_file_name: str | None = None,
        target_url: str | None = None,
        provider: str = "gohighlevel",
        location_id: str = "",
        access_token: str = "",
        platforms: tuple[str, ...] = (),
        user_id: str | None = None,
        source_site_id: str | None = None,
        social_post_type: str = "reel",
        artifact_kind: str = "reel_video",
    ) -> None:
        resolved_media_path = media_path or video_path
        if resolved_media_path is None:
            raise TypeError("MultiPlatformPublishRequest requires a media_path.")

        object.__setattr__(self, "media_path", Path(resolved_media_path))
        object.__setattr__(self, "descriptions_by_platform", dict(descriptions_by_platform or {}))
        object.__setattr__(self, "titles_by_platform", dict(titles_by_platform or {}))
        object.__setattr__(self, "upload_file_name", upload_file_name)
        object.__setattr__(self, "target_url", target_url)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "location_id", location_id)
        object.__setattr__(self, "access_token", access_token)
        object.__setattr__(self, "platforms", tuple(platforms))
        object.__setattr__(self, "user_id", user_id)
        object.__setattr__(self, "source_site_id", source_site_id)
        object.__setattr__(self, "social_post_type", social_post_type)
        object.__setattr__(self, "artifact_kind", artifact_kind)

    @property
    def video_path(self) -> Path:
        return self.media_path


@dataclass(frozen=True, slots=True)
class MultiPlatformPublishResult:
    desired_platforms: tuple[str, ...]
    platform_results: tuple[PlatformPublishOutcome, ...]
    selected_user: LocationUser | None
    uploaded_media: UploadedMedia | None
    source_site_id: str | None
    target_url: str | None
    social_post_type: str
    artifact_kind: str

    @property
    def successful_platforms(self) -> tuple[str, ...]:
        return tuple(
            outcome.platform
            for outcome in self.platform_results
            if outcome.is_success
        )

    @property
    def has_any_success(self) -> bool:
        return bool(self.successful_platforms)

    @property
    def aggregate_status(self) -> str:
        if not self.desired_platforms:
            return "skipped"
        if not self.has_any_success:
            return "failed"
        if len(self.successful_platforms) == len(self.desired_platforms):
            return "published"
        return "partial"

    @property
    def should_retry(self) -> bool:
        return (
            not self.has_any_success
            and any(outcome.retryable for outcome in self.platform_results)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregate_status": self.aggregate_status,
            "desired_platforms": list(self.desired_platforms),
            "successful_platforms": list(self.successful_platforms),
            "selected_user_id": self.selected_user.id if self.selected_user is not None else None,
            "selected_user_display_name": (
                self.selected_user.display_name if self.selected_user is not None else None
            ),
            "uploaded_media_url": self.uploaded_media.url if self.uploaded_media is not None else None,
            "uploaded_media_file_id": (
                self.uploaded_media.file_id if self.uploaded_media is not None else None
            ),
            "artifact_kind": self.artifact_kind,
            "social_post_type": self.social_post_type,
            "target_url": self.target_url,
            "platform_results": {
                outcome.platform: outcome.to_dict()
                for outcome in self.platform_results
            },
        }


PublishVideoRequest = PublishMediaRequest
PublishVideoResult = PublishMediaResult


__all__ = [
    "CreatedSocialPost",
    "FAILED_PLATFORM_OUTCOMES",
    "LocationUser",
    "MultiPlatformPublishRequest",
    "MultiPlatformPublishResult",
    "PlatformPublishOutcome",
    "PublishMediaRequest",
    "PublishMediaResult",
    "PublishVideoRequest",
    "PublishVideoResult",
    "SocialAccount",
    "SUCCESSFUL_PLATFORM_OUTCOMES",
    "UploadedMedia",
]
